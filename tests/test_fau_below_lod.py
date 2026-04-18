"""Tests for qualitative value handling in save_wyniki (FAU <1 flow)."""
import json
import sqlite3
import pytest

from mbr.models import init_mbr_tables
from mbr.laborant.models import save_wyniki, get_ebr_wyniki


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _setup_ebr_with_fau(db) -> int:
    """Create an MBR + EBR with metnosc_fau in analiza_koncowa."""
    parametry_lab = {
        "analiza_koncowa": {
            "pola": [
                {"kod": "metnosc_fau", "tag": "metnosc_fau", "precision": 1, "min": 0, "max": 50},
                {"kod": "ph", "tag": "ph", "precision": 2, "min": 6, "max": 8},
            ],
        },
    }
    cur = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, dt_utworzenia) "
        "VALUES ('TestFAU', 1, 'active', '[]', ?, datetime('now'))",
        (json.dumps(parametry_lab),),
    )
    mbr_id = cur.lastrowid
    cur = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status) "
        "VALUES (?, 'B001', '1/2026', datetime('now'), 'open')",
        (mbr_id,),
    )
    db.commit()
    return cur.lastrowid


def test_save_wyniki_stores_lod_prefix_in_wartosc_text(db):
    """Value '<1' saves as wartosc_text, wartosc=NULL."""
    ebr_id = _setup_ebr_with_fau(db)
    save_wyniki(db, ebr_id, "analiza_koncowa",
                {"metnosc_fau": {"wartosc": "<1", "komentarz": ""}},
                "testuser")
    row = db.execute(
        "SELECT wartosc, wartosc_text, w_limicie FROM ebr_wyniki "
        "WHERE ebr_id=? AND kod_parametru='metnosc_fau'",
        (ebr_id,),
    ).fetchone()
    assert row is not None
    assert row["wartosc"] is None
    assert row["wartosc_text"] == "<1"
    assert row["w_limicie"] is None  # neutral — nie oceniamy jakościowo


def test_save_wyniki_numeric_clears_wartosc_text(db):
    """Numeric value overwrites previous qualitative state."""
    ebr_id = _setup_ebr_with_fau(db)
    save_wyniki(db, ebr_id, "analiza_koncowa",
                {"metnosc_fau": {"wartosc": "<1", "komentarz": ""}},
                "u1")
    save_wyniki(db, ebr_id, "analiza_koncowa",
                {"metnosc_fau": {"wartosc": "3,5", "komentarz": ""}},
                "u2")
    row = db.execute(
        "SELECT wartosc, wartosc_text FROM ebr_wyniki "
        "WHERE ebr_id=? AND kod_parametru='metnosc_fau'",
        (ebr_id,),
    ).fetchone()
    assert row["wartosc"] == 3.5
    assert row["wartosc_text"] is None


def test_save_wyniki_supports_all_comparison_prefixes(db):
    """Prefixes <, >, ≤, ≥ all route to wartosc_text."""
    ebr_id = _setup_ebr_with_fau(db)
    for val in ["<1", ">50", "≤1", "≥50"]:
        save_wyniki(db, ebr_id, "analiza_koncowa",
                    {"metnosc_fau": {"wartosc": val, "komentarz": ""}},
                    "u")
        row = db.execute(
            "SELECT wartosc, wartosc_text FROM ebr_wyniki "
            "WHERE ebr_id=? AND kod_parametru='metnosc_fau'",
            (ebr_id,),
        ).fetchone()
        assert row["wartosc"] is None, f"wartosc not None for {val}"
        assert row["wartosc_text"] == val


def test_save_wyniki_rejects_junk_text(db):
    """Plain non-numeric, non-prefix text is still rejected (silent skip)."""
    ebr_id = _setup_ebr_with_fau(db)
    save_wyniki(db, ebr_id, "analiza_koncowa",
                {"metnosc_fau": {"wartosc": "abc", "komentarz": ""}},
                "u")
    row = db.execute(
        "SELECT wartosc, wartosc_text FROM ebr_wyniki "
        "WHERE ebr_id=? AND kod_parametru='metnosc_fau'",
        (ebr_id,),
    ).fetchone()
    assert row is None, "junk text should not create a row"


def test_save_wyniki_numeric_unchanged_behavior(db):
    """Normal numeric flow still works."""
    ebr_id = _setup_ebr_with_fau(db)
    save_wyniki(db, ebr_id, "analiza_koncowa",
                {"ph": {"wartosc": "7,20", "komentarz": ""}},
                "u")
    row = db.execute(
        "SELECT wartosc, wartosc_text, w_limicie FROM ebr_wyniki "
        "WHERE ebr_id=? AND kod_parametru='ph'",
        (ebr_id,),
    ).fetchone()
    assert row["wartosc"] == 7.20
    assert row["wartosc_text"] is None
    assert row["w_limicie"] == 1
