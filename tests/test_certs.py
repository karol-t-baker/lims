"""Tests for mbr.certs.models."""

import sqlite3
import pytest
from mbr.models import init_mbr_tables
from mbr.certs.models import create_swiadectwo, list_swiadectwa, mark_swiadectwa_outdated


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _insert_mbr(db, produkt="TestProd"):
    cur = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "dt_utworzenia) VALUES (?, 1, 'active', '[]', '{}', datetime('now'))",
        (produkt,),
    )
    db.commit()
    return cur.lastrowid


def _insert_ebr(db, mbr_id, batch_id="B001", nr_partii="1/2026"):
    cur = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status) "
        "VALUES (?, ?, ?, datetime('now'), 'completed')",
        (mbr_id, batch_id, nr_partii),
    )
    db.commit()
    return cur.lastrowid


@pytest.fixture
def ebr_id(db):
    mbr_id = _insert_mbr(db)
    return _insert_ebr(db, mbr_id)


# ---------------------------------------------------------------------------
# create_swiadectwo
# ---------------------------------------------------------------------------

def test_create_swiadectwo_returns_id(db, ebr_id):
    sw_id = create_swiadectwo(db, ebr_id, "szablon_A", "1/2026", "/path/cert.pdf", "jan.kowalski")
    assert isinstance(sw_id, int)
    assert sw_id > 0


def test_create_swiadectwo_persists_record(db, ebr_id):
    create_swiadectwo(db, ebr_id, "szablon_A", "1/2026", "/path/cert.pdf", "jan.kowalski")
    rows = list_swiadectwa(db, ebr_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["template_name"] == "szablon_A"
    assert row["nr_partii"] == "1/2026"
    assert row["pdf_path"] == "/path/cert.pdf"
    assert row["wystawil"] == "jan.kowalski"
    assert row["nieaktualne"] == 0


def test_create_swiadectwo_sets_dt_wystawienia(db, ebr_id):
    create_swiadectwo(db, ebr_id, "T", "1/2026", "/p.pdf", "user")
    rows = list_swiadectwa(db, ebr_id)
    assert rows[0]["dt_wystawienia"] is not None


# ---------------------------------------------------------------------------
# list_swiadectwa
# ---------------------------------------------------------------------------

def test_list_swiadectwa_empty_when_none(db, ebr_id):
    assert list_swiadectwa(db, ebr_id) == []


def test_list_swiadectwa_returns_only_for_given_ebr(db):
    mbr_id = _insert_mbr(db, produkt="OtherProd")
    ebr1 = _insert_ebr(db, mbr_id, batch_id="B100", nr_partii="1/2026")
    ebr2 = _insert_ebr(db, mbr_id, batch_id="B200", nr_partii="2/2026")
    create_swiadectwo(db, ebr1, "T", "1/2026", "/a.pdf", "user")
    create_swiadectwo(db, ebr2, "T", "2/2026", "/b.pdf", "user")
    assert len(list_swiadectwa(db, ebr1)) == 1
    assert len(list_swiadectwa(db, ebr2)) == 1


def test_list_swiadectwa_ordered_desc(db, ebr_id):
    create_swiadectwo(db, ebr_id, "T1", "1/2026", "/a.pdf", "user")
    create_swiadectwo(db, ebr_id, "T2", "1/2026", "/b.pdf", "user")
    rows = list_swiadectwa(db, ebr_id)
    assert len(rows) == 2
    # Both records are returned regardless of order (same-second timestamps in tests)
    names = {r["template_name"] for r in rows}
    assert names == {"T1", "T2"}


# ---------------------------------------------------------------------------
# mark_swiadectwa_outdated
# ---------------------------------------------------------------------------

def test_mark_swiadectwa_outdated_sets_flag(db, ebr_id):
    create_swiadectwo(db, ebr_id, "T", "1/2026", "/a.pdf", "user")
    mark_swiadectwa_outdated(db, ebr_id)
    rows = list_swiadectwa(db, ebr_id)
    assert rows[0]["nieaktualne"] == 1


def test_mark_swiadectwa_outdated_marks_all(db, ebr_id):
    create_swiadectwo(db, ebr_id, "T1", "1/2026", "/a.pdf", "user")
    create_swiadectwo(db, ebr_id, "T2", "1/2026", "/b.pdf", "user")
    mark_swiadectwa_outdated(db, ebr_id)
    rows = list_swiadectwa(db, ebr_id)
    assert all(r["nieaktualne"] == 1 for r in rows)


def test_mark_swiadectwa_outdated_idempotent(db, ebr_id):
    create_swiadectwo(db, ebr_id, "T", "1/2026", "/a.pdf", "user")
    mark_swiadectwa_outdated(db, ebr_id)
    mark_swiadectwa_outdated(db, ebr_id)  # second call should not error
    rows = list_swiadectwa(db, ebr_id)
    assert rows[0]["nieaktualne"] == 1


def test_mark_swiadectwa_outdated_does_not_affect_other_ebr(db):
    mbr_id = _insert_mbr(db, produkt="P2")
    ebr1 = _insert_ebr(db, mbr_id, batch_id="B300", nr_partii="3/2026")
    ebr2 = _insert_ebr(db, mbr_id, batch_id="B400", nr_partii="4/2026")
    create_swiadectwo(db, ebr1, "T", "3/2026", "/a.pdf", "user")
    create_swiadectwo(db, ebr2, "T", "4/2026", "/b.pdf", "user")
    mark_swiadectwa_outdated(db, ebr1)
    assert list_swiadectwa(db, ebr2)[0]["nieaktualne"] == 0


# ---------------------------------------------------------------------------
# cert_settings
# ---------------------------------------------------------------------------

def test_cert_settings_table_exists(db):
    """init_mbr_tables must create cert_settings."""
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='cert_settings'"
    ).fetchall()
    assert len(rows) == 1


def test_cert_settings_default_seed(db):
    """Defaults must be seeded on first init."""
    rows = dict(db.execute("SELECT key, value FROM cert_settings").fetchall())
    assert rows["body_font_family"] == "TeX Gyre Bonum"
    assert rows["header_font_size_pt"] == "14"


def test_cert_settings_init_idempotent(db):
    """Re-running init_mbr_tables doesn't duplicate seed rows."""
    from mbr.models import init_mbr_tables
    init_mbr_tables(db)
    init_mbr_tables(db)
    rows = db.execute("SELECT key FROM cert_settings").fetchall()
    keys = [r["key"] for r in rows]
    assert len(keys) == len(set(keys)), f"duplicate keys: {keys}"


def test_load_cert_settings_returns_seeded_defaults(db):
    from mbr.certs.generator import _load_cert_settings
    s = _load_cert_settings(db)
    assert s["body_font_family"] == "TeX Gyre Bonum"
    assert s["header_font_size_pt"] == 14  # int, parsed from "14"


def test_load_cert_settings_reads_override(db):
    db.execute("UPDATE cert_settings SET value=? WHERE key=?", ("EB Garamond", "body_font_family"))
    db.execute("UPDATE cert_settings SET value=? WHERE key=?", ("18", "header_font_size_pt"))
    db.commit()
    from mbr.certs.generator import _load_cert_settings
    s = _load_cert_settings(db)
    assert s["body_font_family"] == "EB Garamond"
    assert s["header_font_size_pt"] == 18


def test_build_preview_context_includes_typography():
    """build_preview_context must surface cert_settings in the render context."""
    product = {
        "display_name": "Test",
        "spec_number": "P001",
        "cas_number": "",
        "expiry_months": 12,
        "opinion_pl": "",
        "opinion_en": "",
        "parameters": [],
        "variants": [{"id": "base", "label": "Test", "flags": [], "overrides": {}}],
    }
    import unittest.mock as mock
    with mock.patch("mbr.certs.generator._load_cert_settings",
                    return_value={"body_font_family": "EB Garamond", "header_font_size_pt": 18}):
        from mbr.certs.generator import build_preview_context
        ctx = build_preview_context(product, "base")
    assert ctx["body_font_family"] == "EB Garamond"
    assert ctx["header_font_size_pt"] == 18


def test_md_to_richtext_pipe_becomes_line_break():
    """'|' in parameter name must split into two lines with <w:br/> between."""
    from mbr.certs.generator import _md_to_richtext
    rt = _md_to_richtext("kokamido|amidoamin")
    xml = str(rt)
    assert "kokamido" in xml and "amidoamin" in xml
    assert "<w:br/>" in xml, f"no line break in: {xml}"


def test_md_to_richtext_pipe_combined_with_sub_super():
    """| must coexist with ^{} / _{} markers."""
    from mbr.certs.generator import _md_to_richtext
    rt = _md_to_richtext("n_{D}^{20}|value")
    xml = str(rt)
    assert "<w:br/>" in xml
    # sub/sup markers should have been expanded (no literal _{ or ^{ left)
    assert "_{" not in xml and "^{" not in xml


def test_md_to_richtext_no_pipe_no_break():
    """Plain text without '|' must not introduce a break."""
    from mbr.certs.generator import _md_to_richtext
    rt = _md_to_richtext("plain text no pipe")
    xml = str(rt)
    assert "<w:br/>" not in xml


def test_md_to_richtext_multiple_pipes():
    """Multiple '|' markers should produce multiple line breaks."""
    from mbr.certs.generator import _md_to_richtext
    rt = _md_to_richtext("line1|line2|line3")
    xml = str(rt)
    # Should have exactly 2 line breaks for 3 lines
    assert xml.count("<w:br/>") == 2
