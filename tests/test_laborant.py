"""Tests for mbr/laborant/models.py — EBR batch management and lab data entry."""

import json
import sqlite3
from datetime import datetime

import pytest

from mbr.models import init_mbr_tables
from mbr.laborant.models import (
    next_nr_partii,
    create_ebr,
    get_ebr,
    get_ebr_wyniki,
    save_wyniki,
    get_round_state,
    complete_ebr,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)

    # Add nr_zbiornika column (not yet in init_mbr_tables CREATE TABLE)
    try:
        conn.execute("ALTER TABLE ebr_batches ADD COLUMN nr_zbiornika TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass  # Already exists

    # Create minimal v4 batch table needed by next_nr_partii
    conn.execute("""
        CREATE TABLE IF NOT EXISTS batch (
            batch_id    TEXT PRIMARY KEY,
            produkt     TEXT,
            nr_partii   TEXT,
            _source     TEXT
        )
    """)
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def db_with_template(db):
    """DB with an active MBR template for TestProduct."""
    now = datetime.now().isoformat(timespec="seconds")
    parametry_lab = json.dumps({
        "analiza": {
            "label": "Analiza",
            "pola": [
                {
                    "kod": "sm",
                    "label": "SM",
                    "tag": "sm",
                    "typ": "float",
                    "min": 40,
                    "max": 48,
                    "precision": 1,
                    "measurement_type": "bezposredni",
                },
                {
                    "kod": "ph",
                    "label": "pH",
                    "tag": "ph",
                    "typ": "float",
                    "min": 5.0,
                    "max": 7.0,
                    "precision": 2,
                    "measurement_type": "bezposredni",
                },
            ],
        }
    })
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia) VALUES (?, 1, 'active', '[]', ?, 'test', ?)",
        ("TestProduct", parametry_lab, now),
    )
    db.commit()
    return db


# ---------------------------------------------------------------------------
# next_nr_partii
# ---------------------------------------------------------------------------

def test_next_nr_partii_first_batch(db):
    nr = next_nr_partii(db, "Chegina_K40GL")
    year = datetime.now().year
    assert nr == f"1/{year}"


def test_next_nr_partii_formatted_correctly(db):
    nr = next_nr_partii(db, "Chegina_K7")
    assert "/" in nr
    parts = nr.split("/")
    assert len(parts) == 2
    assert parts[0].isdigit()
    assert parts[1].isdigit()


def test_next_nr_partii_increments_from_existing(db):
    """When a batch already exists, next number should be one higher."""
    year = datetime.now().year
    now = datetime.now().isoformat(timespec="seconds")
    # Insert a fake MBR template and EBR batch
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia) VALUES (?, 1, 'active', '[]', '{}', 'test', ?)",
        ("Chegina_K40GL", now),
    )
    db.commit()
    mbr_id = db.execute("SELECT mbr_id FROM mbr_templates WHERE produkt='Chegina_K40GL'").fetchone()["mbr_id"]
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, typ) "
        "VALUES (?, ?, ?, ?, 'open', 'szarza')",
        (mbr_id, f"Chegina_K40GL__5_{year}", f"5/{year}", now),
    )
    db.commit()

    nr = next_nr_partii(db, "Chegina_K40GL")
    assert nr == f"6/{year}"


# ---------------------------------------------------------------------------
# create_ebr
# ---------------------------------------------------------------------------

def test_create_ebr_returns_none_without_active_mbr(db):
    result = create_ebr(db, "NoTemplate", "1/2026", "A1", "M1", 1000.0, "operator")
    assert result is None


def test_create_ebr_returns_ebr_id(db_with_template):
    db = db_with_template
    ebr_id = create_ebr(db, "TestProduct", "1/2026", "A1", "M1", 1000.0, "operator")
    assert isinstance(ebr_id, int)
    assert ebr_id > 0


def test_create_ebr_stores_batch_id(db_with_template):
    db = db_with_template
    ebr_id = create_ebr(db, "TestProduct", "2/2026", "A2", "M2", 500.0, "lab")

    row = db.execute("SELECT batch_id FROM ebr_batches WHERE ebr_id = ?", (ebr_id,)).fetchone()
    assert row["batch_id"] == "TestProduct__2_2026"


def test_create_ebr_status_is_open(db_with_template):
    db = db_with_template
    ebr_id = create_ebr(db, "TestProduct", "3/2026", "A3", "M3", None, "op")

    row = db.execute("SELECT status FROM ebr_batches WHERE ebr_id = ?", (ebr_id,)).fetchone()
    assert row["status"] == "open"


# ---------------------------------------------------------------------------
# get_ebr
# ---------------------------------------------------------------------------

def test_get_ebr_returns_dict_with_mbr_data(db_with_template):
    db = db_with_template
    ebr_id = create_ebr(db, "TestProduct", "4/2026", "A4", "M4", 800.0, "op")

    ebr = get_ebr(db, ebr_id)
    assert ebr is not None
    assert isinstance(ebr, dict)
    assert ebr["ebr_id"] == ebr_id
    assert ebr["produkt"] == "TestProduct"
    assert "parametry_lab" in ebr
    assert "etapy_json" in ebr


def test_get_ebr_returns_none_for_unknown_id(db):
    assert get_ebr(db, 9999) is None


def test_get_ebr_nr_partii_matches(db_with_template):
    db = db_with_template
    ebr_id = create_ebr(db, "TestProduct", "5/2026", "A5", "M5", 1200.0, "op")
    ebr = get_ebr(db, ebr_id)
    assert ebr["nr_partii"] == "5/2026"


# ---------------------------------------------------------------------------
# get_ebr_wyniki
# ---------------------------------------------------------------------------

def test_get_ebr_wyniki_empty_for_new_batch(db_with_template):
    db = db_with_template
    ebr_id = create_ebr(db, "TestProduct", "6/2026", "A6", "M6", 1000.0, "op")
    wyniki = get_ebr_wyniki(db, ebr_id)
    assert wyniki == {}


def test_get_ebr_wyniki_returns_dict_after_save(db_with_template):
    db = db_with_template
    ebr_id = create_ebr(db, "TestProduct", "7/2026", "A7", "M7", 1000.0, "op")
    ebr = get_ebr(db, ebr_id)

    save_wyniki(db, ebr_id, "analiza__1",
                {"sm": {"wartosc": 44.0, "komentarz": ""}},
                user="lab", ebr=ebr)

    wyniki = get_ebr_wyniki(db, ebr_id)
    assert "analiza__1" in wyniki
    assert "sm" in wyniki["analiza__1"]


def test_get_ebr_wyniki_nested_structure(db_with_template):
    db = db_with_template
    ebr_id = create_ebr(db, "TestProduct", "8/2026", "A8", "M8", 1000.0, "op")
    ebr = get_ebr(db, ebr_id)

    save_wyniki(db, ebr_id, "analiza__1",
                {"sm": {"wartosc": 45.0, "komentarz": "ok"}},
                user="lab", ebr=ebr)

    wyniki = get_ebr_wyniki(db, ebr_id)
    entry = wyniki["analiza__1"]["sm"]
    assert "wartosc" in entry
    assert "w_limicie" in entry
    assert "sekcja" in entry


# ---------------------------------------------------------------------------
# save_wyniki — w_limicie computation
# ---------------------------------------------------------------------------

def test_save_wyniki_in_range_sets_w_limicie_1(db_with_template):
    """Value within [min, max] → w_limicie = 1."""
    db = db_with_template
    ebr_id = create_ebr(db, "TestProduct", "9/2026", "A9", "M9", 1000.0, "op")
    ebr = get_ebr(db, ebr_id)

    # sm: min=40, max=48 — value 44.0 is in range
    save_wyniki(db, ebr_id, "analiza__1",
                {"sm": {"wartosc": 44.0, "komentarz": ""}},
                user="lab", ebr=ebr)

    wyniki = get_ebr_wyniki(db, ebr_id)
    assert wyniki["analiza__1"]["sm"]["w_limicie"] == 1


def test_save_wyniki_below_min_sets_w_limicie_0(db_with_template):
    """Value below min → w_limicie = 0."""
    db = db_with_template
    ebr_id = create_ebr(db, "TestProduct", "10/2026", "A10", "M10", 1000.0, "op")
    ebr = get_ebr(db, ebr_id)

    # sm: min=40 — value 38.0 is out of range
    save_wyniki(db, ebr_id, "analiza__1",
                {"sm": {"wartosc": 38.0, "komentarz": ""}},
                user="lab", ebr=ebr)

    wyniki = get_ebr_wyniki(db, ebr_id)
    assert wyniki["analiza__1"]["sm"]["w_limicie"] == 0


def test_save_wyniki_above_max_sets_w_limicie_0(db_with_template):
    """Value above max → w_limicie = 0."""
    db = db_with_template
    ebr_id = create_ebr(db, "TestProduct", "11/2026", "A11", "M11", 1000.0, "op")
    ebr = get_ebr(db, ebr_id)

    # sm: max=48 — value 50.0 is out of range
    save_wyniki(db, ebr_id, "analiza__1",
                {"sm": {"wartosc": 50.0, "komentarz": ""}},
                user="lab", ebr=ebr)

    wyniki = get_ebr_wyniki(db, ebr_id)
    assert wyniki["analiza__1"]["sm"]["w_limicie"] == 0


def test_save_wyniki_unknown_kod_skipped(db_with_template):
    """Kod not in pola_map is silently skipped."""
    db = db_with_template
    ebr_id = create_ebr(db, "TestProduct", "12/2026", "A12", "M12", 1000.0, "op")
    ebr = get_ebr(db, ebr_id)

    save_wyniki(db, ebr_id, "analiza__1",
                {"unknown_field": {"wartosc": 99.9, "komentarz": ""}},
                user="lab", ebr=ebr)

    wyniki = get_ebr_wyniki(db, ebr_id)
    assert "analiza__1" not in wyniki or "unknown_field" not in wyniki.get("analiza__1", {})


def test_save_wyniki_upsert_updates_value(db_with_template):
    """Second save with same (ebr_id, sekcja, kod) updates the value."""
    db = db_with_template
    ebr_id = create_ebr(db, "TestProduct", "13/2026", "A13", "M13", 1000.0, "op")
    ebr = get_ebr(db, ebr_id)

    save_wyniki(db, ebr_id, "analiza__1",
                {"sm": {"wartosc": 42.0, "komentarz": "first"}},
                user="lab", ebr=ebr)
    save_wyniki(db, ebr_id, "analiza__1",
                {"sm": {"wartosc": 44.5, "komentarz": "updated"}},
                user="lab2", ebr=ebr)

    wyniki = get_ebr_wyniki(db, ebr_id)
    assert wyniki["analiza__1"]["sm"]["wartosc"] == pytest.approx(44.5)


# ---------------------------------------------------------------------------
# get_round_state
# ---------------------------------------------------------------------------

def test_get_round_state_empty_wyniki(db):
    state = get_round_state({})
    assert state["last_analiza"] == 0
    assert state["last_dodatki"] == 0
    assert state["next_step"] == "analiza"
    assert state["next_sekcja"] == "analiza__1"
    assert state["is_decision"] is False


def test_get_round_state_after_first_analiza(db):
    wyniki = {"analiza__1": {"sm": {"w_limicie": 1}}}
    state = get_round_state(wyniki)
    assert state["last_analiza"] == 1
    assert state["next_step"] == "dodatki"
    assert state["next_sekcja"] == "dodatki__1"


def test_get_round_state_after_analiza_and_dodatki(db):
    wyniki = {
        "analiza__1": {"sm": {"w_limicie": 1}},
        "dodatki__1": {"woda_kg": {"w_limicie": 1}},
    }
    state = get_round_state(wyniki)
    assert state["next_step"] == "analiza"
    assert state["next_sekcja"] == "analiza__2"


def test_get_round_state_is_decision_after_second_analiza(db):
    """is_decision=True when analiza round >= 2 and no pending dodatki."""
    wyniki = {
        "analiza__1": {"sm": {"w_limicie": 1}},
        "dodatki__1": {},
        "analiza__2": {"sm": {"w_limicie": 1}},
    }
    state = get_round_state(wyniki)
    assert state["is_decision"] is True
    assert state["last_analiza"] == 2


def test_get_round_state_prev_analiza_out(db):
    """prev_analiza_out lists kods with w_limicie=0 in last analiza."""
    wyniki = {
        "analiza__1": {
            "sm": {"w_limicie": 0},
            "ph": {"w_limicie": 1},
        }
    }
    state = get_round_state(wyniki)
    assert "sm" in state["prev_analiza_out"]
    assert "ph" not in state["prev_analiza_out"]


# ---------------------------------------------------------------------------
# complete_ebr
# ---------------------------------------------------------------------------

def test_complete_ebr_sets_status_completed(db_with_template):
    db = db_with_template
    ebr_id = create_ebr(db, "TestProduct", "14/2026", "A14", "M14", 1000.0, "op")

    complete_ebr(db, ebr_id)

    row = db.execute("SELECT status FROM ebr_batches WHERE ebr_id = ?", (ebr_id,)).fetchone()
    assert row["status"] == "completed"


def test_complete_ebr_sets_dt_end(db_with_template):
    db = db_with_template
    ebr_id = create_ebr(db, "TestProduct", "15/2026", "A15", "M15", 1000.0, "op")

    complete_ebr(db, ebr_id)

    row = db.execute("SELECT dt_end FROM ebr_batches WHERE ebr_id = ?", (ebr_id,)).fetchone()
    assert row["dt_end"] is not None


def test_complete_ebr_saves_zbiorniki(db_with_template):
    db = db_with_template
    ebr_id = create_ebr(db, "TestProduct", "16/2026", "A16", "M16", 1000.0, "op")

    zbiorniki = [{"zbiornik": "M16", "kg": 500}]
    complete_ebr(db, ebr_id, zbiorniki=zbiorniki)

    row = db.execute("SELECT przepompowanie_json FROM ebr_batches WHERE ebr_id = ?", (ebr_id,)).fetchone()
    assert row["przepompowanie_json"] is not None
    saved = json.loads(row["przepompowanie_json"])
    assert saved[0]["zbiornik"] == "M16"
