"""Backend regression: jakosciowy w_limicie should be NULL when
opisowe_wartosci is empty/NULL (no spec list = neutral, not 'out of spec')."""

import json
import sqlite3
import pytest

from mbr.models import init_mbr_tables
from mbr.laborant.models import save_wyniki


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed_jakosciowy_param(db, kod, opisowe_wartosci):
    """Returns ebr_id ready for save_wyniki call."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision, "
        "opisowe_wartosci) VALUES (?, ?, 'jakosciowy', 'lab', 0, ?)",
        (kod, kod.capitalize(), opisowe_wartosci),
    )
    db.execute("INSERT OR IGNORE INTO produkty (nazwa, display_name) VALUES ('P', 'P')")
    db.execute(
        "INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, "
        "etapy_json, parametry_lab, dt_utworzenia) VALUES (1, 'P', 1, 'active', '[]', '{}', '2026-01-01')"
    )
    db.execute(
        "INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start) "
        "VALUES (1, 1, 'P_b1', '1/26', '2026-01-01T00:00:00')"
    )
    db.commit()
    return 1  # ebr_id


def test_w_limicie_null_when_opisowe_wartosci_empty(db):
    """When parametry_analityczne.opisowe_wartosci is NULL, an explicit
    wartosc_text save must produce w_limicie=NULL (not 0)."""
    ebr_id = _seed_jakosciowy_param(db, "test_kod", None)

    save_wyniki(
        db, ebr_id=ebr_id, sekcja="analiza",
        values={"test_kod": {"wartosc_text": "<1|45|22"}},
        user="op",
    )

    row = db.execute(
        "SELECT w_limicie, wartosc_text FROM ebr_wyniki WHERE kod_parametru='test_kod'"
    ).fetchone()
    assert row["wartosc_text"] == "<1|45|22"
    assert row["w_limicie"] is None  # neutral — no spec to validate against


def test_w_limicie_set_when_opisowe_wartosci_present(db):
    """Existing semantics preserved: with a defined opisowe_wartosci list,
    in-list value → w_limicie=1, out-of-list → w_limicie=0."""
    ebr_id = _seed_jakosciowy_param(db, "test_kod", json.dumps(["OK", "nieOK"]))

    save_wyniki(
        db, ebr_id=ebr_id, sekcja="analiza",
        values={"test_kod": {"wartosc_text": "OK"}},
        user="op",
    )

    row = db.execute(
        "SELECT w_limicie FROM ebr_wyniki WHERE kod_parametru='test_kod'"
    ).fetchone()
    assert row["w_limicie"] == 1

    save_wyniki(
        db, ebr_id=ebr_id, sekcja="analiza",
        values={"test_kod": {"wartosc_text": "nieZdefiniowane"}},
        user="op",
    )

    row = db.execute(
        "SELECT w_limicie FROM ebr_wyniki WHERE kod_parametru='test_kod'"
    ).fetchone()
    assert row["w_limicie"] == 0
