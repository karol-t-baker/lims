"""save_wyniki with empty wartosc clears the row to NULL.

Bug: laborant edits a parameter on a completed batch, deletes the digit so the
field is empty, blurs/saves. Expected: value is wiped (NULL in ebr_wyniki).
Actual (before fix): backend skips empty raw_str (`float("")` raises, hits
`continue`), so the prior value stays in the DB and reappears after refresh.
"""
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


def _setup_ebr(db) -> int:
    parametry_lab = {
        "analiza_koncowa": {
            "pola": [
                {"kod": "ph", "tag": "ph", "precision": 2, "min": 6, "max": 8},
            ],
        },
    }
    cur = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, dt_utworzenia) "
        "VALUES ('TestClear', 1, 'active', '[]', ?, datetime('now'))",
        (json.dumps(parametry_lab),),
    )
    mbr_id = cur.lastrowid
    cur = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status) "
        "VALUES (?, 'B001', '1/2026', datetime('now'), 'completed')",
        (mbr_id,),
    )
    db.commit()
    return cur.lastrowid


def test_empty_wartosc_clears_existing_row_to_null(db):
    """Existing numeric value → save with wartosc='' → row becomes NULL/NULL/NULL."""
    ebr_id = _setup_ebr(db)
    # First: store a value.
    save_wyniki(db, ebr_id, "analiza_koncowa",
                {"ph": {"wartosc": "7,2", "komentarz": ""}},
                "u1")
    row = db.execute(
        "SELECT wartosc, wartosc_text, w_limicie FROM ebr_wyniki "
        "WHERE ebr_id=? AND kod_parametru='ph'",
        (ebr_id,),
    ).fetchone()
    assert row["wartosc"] == 7.2

    # Now: laborant clears the field.
    save_wyniki(db, ebr_id, "analiza_koncowa",
                {"ph": {"wartosc": "", "komentarz": ""}},
                "u2")

    row = db.execute(
        "SELECT wartosc, wartosc_text, w_limicie FROM ebr_wyniki "
        "WHERE ebr_id=? AND kod_parametru='ph'",
        (ebr_id,),
    ).fetchone()
    assert row is not None, "row must still exist (audit trail)"
    assert row["wartosc"] is None
    assert row["wartosc_text"] is None
    assert row["w_limicie"] is None  # neutral — nothing to evaluate


def test_empty_wartosc_logs_diff_for_audit(db):
    """Clearing a value must show up in the diff list (audit log carrier)."""
    ebr_id = _setup_ebr(db)
    save_wyniki(db, ebr_id, "analiza_koncowa",
                {"ph": {"wartosc": "7,2", "komentarz": ""}},
                "u1")

    result = save_wyniki(db, ebr_id, "analiza_koncowa",
                         {"ph": {"wartosc": "", "komentarz": ""}},
                         "u2")

    assert result["has_updates"] is True
    diffs = result["diffs"]
    ph_diff = next((d for d in diffs if d["pole"] == "ph"), None)
    assert ph_diff is not None, "diff for ph must be present after clearing"
    assert ph_diff["stara"] == 7.2
    assert ph_diff["nowa"] is None
