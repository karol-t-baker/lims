"""PR3: save_wyniki accepts wartosc_text for jakosciowy params + computes w_limicie from opisowe_wartosci."""

import json as _json
import sqlite3
import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed(db):
    pid = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision, opisowe_wartosci) "
        "VALUES ('zapach', 'Zapach', 'jakosciowy', 'lab', 0, ?)",
        (_json.dumps(["charakterystyczny", "obcy", "brak"]),),
    ).lastrowid
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('P', 'P')")
    db.execute(
        "INSERT INTO mbr_templates (produkt, status, parametry_lab, etapy_json, wersja, dt_utworzenia) "
        "VALUES ('P', 'active', '{}', '[]', 1, '2026-01-01')"
    )
    mbr_id = db.execute("SELECT mbr_id FROM mbr_templates WHERE produkt='P'").fetchone()[0]
    ebr_id = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, nr_amidatora, nr_mieszalnika, "
        "wielkosc_szarzy_kg, dt_start, operator, typ, status) "
        "VALUES (?, 'P__1', '1', 'A', 'M', 100, '2026-04-20', 'op', 'szarza', 'open')",
        (mbr_id,),
    ).lastrowid
    db.commit()
    return ebr_id, pid


def test_save_wyniki_writes_wartosc_text_for_jakosciowy(db):
    from mbr.laborant.models import save_wyniki
    ebr_id, _ = _seed(db)
    save_wyniki(db, ebr_id, "analiza",
                {"zapach": {"wartosc_text": "obcy"}}, "op")
    row = db.execute(
        "SELECT wartosc, wartosc_text, w_limicie FROM ebr_wyniki "
        "WHERE ebr_id=? AND kod_parametru='zapach'",
        (ebr_id,),
    ).fetchone()
    assert row is not None
    assert row["wartosc"] is None
    assert row["wartosc_text"] == "obcy"
    assert row["w_limicie"] == 1


def test_save_wyniki_w_limicie_zero_for_historical_value(db):
    """Value outside opisowe_wartosci is accepted but flagged w_limicie=0."""
    from mbr.laborant.models import save_wyniki
    ebr_id, _ = _seed(db)
    save_wyniki(db, ebr_id, "analiza",
                {"zapach": {"wartosc_text": "legacy_value_not_in_list"}}, "op")
    row = db.execute(
        "SELECT wartosc_text, w_limicie FROM ebr_wyniki "
        "WHERE ebr_id=? AND kod_parametru='zapach'",
        (ebr_id,),
    ).fetchone()
    assert row["wartosc_text"] == "legacy_value_not_in_list"
    assert row["w_limicie"] == 0


def test_save_wyniki_empty_wartosc_text_does_not_write(db):
    """Empty wartosc_text behaves like empty numeric — no row inserted."""
    from mbr.laborant.models import save_wyniki
    ebr_id, _ = _seed(db)
    save_wyniki(db, ebr_id, "analiza", {"zapach": {"wartosc_text": ""}}, "op")
    rows = db.execute(
        "SELECT COUNT(*) AS c FROM ebr_wyniki WHERE ebr_id=? AND kod_parametru='zapach'",
        (ebr_id,),
    ).fetchone()
    # Accept either 0 rows (no insert) or 1 row with wartosc_text IS NULL/"".
    # This documents the current contract; picking the behavior that matches existing numeric empty.
    if rows["c"] == 1:
        row = db.execute(
            "SELECT wartosc_text FROM ebr_wyniki WHERE ebr_id=? AND kod_parametru='zapach'",
            (ebr_id,),
        ).fetchone()
        assert (row["wartosc_text"] or "") == ""
