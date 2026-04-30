"""Tests for rozkład kwasów composite parameter input flow."""

import re
import sqlite3
import pytest
from pathlib import Path

from mbr.models import init_mbr_tables


REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "mbr" / "templates" / "laborant" / "_fast_entry_content.html"


def test_rozklad_template_constants_present():
    """Smoke: the special-case kod and all 9 chain labels must exist
    verbatim in the laborant fast-entry template. Catches regressions
    if anyone refactors the constants away."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "cert_qual_rozklad_kwasow" in text, "ROZKLAD_KOD constant missing"

    expected_chains = [
        "≤C6:0", "C8:0", "C10:0",
        "C12:0", "C14:0", "C16:0",
        "C18:0", "C18:1", "C18:2",
    ]
    for chain in expected_chains:
        assert chain in text, f"chain label {chain!r} missing from template"

    assert "ROZKLAD_KOD" in text, "ROZKLAD_KOD reference missing in JS branch"
    assert "ff-rozklad-grid" in text, "grid CSS class missing"


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def test_wartosc_text_roundtrip_with_pipes(db):
    """Pipe-separated wartosc_text must survive insert/read round-trip
    without any character-level mangling by SQLite or the model layer."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision) "
        "VALUES ('cert_qual_rozklad_kwasow', 'Rozkład', 'jakosciowy', 'zewn', 0)"
    )
    db.execute("INSERT OR IGNORE INTO produkty (nazwa, display_name) VALUES ('Monamid_KO', 'Monamid KO')")
    db.execute(
        "INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, dt_utworzenia, "
        "etapy_json, parametry_lab) "
        "VALUES (1, 'Monamid_KO', 1, 'active', '2026-01-01', '[]', '{}')"
    )
    db.execute(
        "INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start) "
        "VALUES (1, 1, 'b1', '1/26', '2026-01-01T00:00:00')"
    )
    pipe_value = "<1|45|22|18|10|3|1|0|0"
    db.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc_text, "
        "is_manual, dt_wpisu, wpisal) VALUES (1, 'analiza_koncowa', "
        "'cert_qual_rozklad_kwasow', 'tag', ?, 1, '2026-01-01T00:00:00', 'op')",
        (pipe_value,),
    )
    db.commit()

    row = db.execute(
        "SELECT wartosc_text FROM ebr_wyniki WHERE kod_parametru='cert_qual_rozklad_kwasow'"
    ).fetchone()
    assert row["wartosc_text"] == pipe_value


def test_cert_renders_pipes_as_line_breaks_for_rozklad():
    """Cert generator must turn 9-segment wartosc_text into 8 <w:br/>
    runs in the result column. Regression for commit d17a08f
    (RichText conversion of result column)."""
    from docxtpl import DocxTemplate
    from mbr.certs.generator import _md_to_richtext

    template = REPO_ROOT / "mbr" / "templates" / "cert_master_template.docx"
    doc = DocxTemplate(str(template))

    ctx = {
        "avon_code": "R26010", "avon_name": "TEST",
        "wzor": "Mxxx", "opinion_pl": "", "opinion_en": "",
        "order_number": "", "spec_number": "", "product_pl": "X", "product_en": "X",
        "inci": "", "nr_partii": "1/26", "dt_produkcji": "01.01.2026",
        "dt_waznosci": "01.01.2028", "dt_wystawienia": "01.01.2026", "wystawil": "X",
        "rspo_text": "", "cas_number": "", "certificate_number": "",
        "rows": [{
            "kod": "rozklad",
            "name_pl": _md_to_richtext("Rozkład kwasów"),
            "name_en": _md_to_richtext("/Fatty acid distribution|≤C6:0|C8:0|C10:0|C12:0|C14:0|C16:0|C18:0|C18:1|C18:2"),
            "requirement": "",
            "method": "GC",
            "result": _md_to_richtext("<1|45|22|18|10|3|1|0|0"),
        }],
        "has_avon_code": True, "has_avon_name": True,
        "display_name": "M", "rspo": "",
    }

    import tempfile, zipfile
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        out_path = tmp.name
    doc.render(ctx)
    doc.save(out_path)

    with zipfile.ZipFile(out_path) as z:
        xml = z.read("word/document.xml").decode("utf-8")

    m = re.search(r"&lt;1.*?</w:p>", xml, re.DOTALL)
    assert m is not None, "result cell with '<1' not found"
    result_block = m.group(0)
    br_count = result_block.count("<w:br/>")
    assert br_count == 8, f"expected 8 <w:br/> in result cell, got {br_count}"
