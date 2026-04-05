"""Tests for mbr.technolog.models."""

import sqlite3
import pytest
from mbr.models import init_mbr_tables
from mbr.technolog.models import (
    list_mbr,
    save_mbr,
    get_mbr,
    get_active_mbr,
    activate_mbr,
    clone_mbr,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _insert_mbr(db, produkt="TestProd", wersja=1, status="draft", etapy="[]", parametry="{}", user="tester"):
    cur = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (produkt, wersja, status, etapy, parametry, user),
    )
    db.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# list_mbr
# ---------------------------------------------------------------------------

def test_list_mbr_empty(db):
    assert list_mbr(db) == []


def test_list_mbr_returns_all(db):
    _insert_mbr(db, produkt="Prod A", wersja=1)
    _insert_mbr(db, produkt="Prod B", wersja=1)
    result = list_mbr(db)
    assert len(result) == 2


def test_list_mbr_ordered_by_produkt_then_wersja_desc(db):
    _insert_mbr(db, produkt="Beta", wersja=1)
    _insert_mbr(db, produkt="Alpha", wersja=2)
    _insert_mbr(db, produkt="Alpha", wersja=1)
    result = list_mbr(db)
    assert result[0]["produkt"] == "Alpha"
    assert result[0]["wersja"] == 2
    assert result[1]["wersja"] == 1
    assert result[2]["produkt"] == "Beta"


# ---------------------------------------------------------------------------
# save_mbr (update draft)
# ---------------------------------------------------------------------------

def test_save_mbr_updates_draft(db):
    mbr_id = _insert_mbr(db, status="draft")
    ok = save_mbr(db, mbr_id, '["etap1"]', '{"ph": {}}', "notatka testowa")
    assert ok is True
    row = get_mbr(db, mbr_id)
    assert row["etapy_json"] == '["etap1"]'
    assert row["notatki"] == "notatka testowa"


def test_save_mbr_rejects_active(db):
    mbr_id = _insert_mbr(db, status="active")
    ok = save_mbr(db, mbr_id, '[]', '{}', "")
    assert ok is False


def test_save_mbr_rejects_archived(db):
    mbr_id = _insert_mbr(db, status="archived")
    ok = save_mbr(db, mbr_id, '[]', '{}', "")
    assert ok is False


def test_save_mbr_nonexistent_returns_false(db):
    ok = save_mbr(db, 9999, '[]', '{}', "")
    assert ok is False


# ---------------------------------------------------------------------------
# get_mbr
# ---------------------------------------------------------------------------

def test_get_mbr_returns_record(db):
    mbr_id = _insert_mbr(db, produkt="ChemiProd", wersja=3)
    row = get_mbr(db, mbr_id)
    assert row is not None
    assert row["produkt"] == "ChemiProd"
    assert row["wersja"] == 3


def test_get_mbr_returns_none_for_missing(db):
    assert get_mbr(db, 9999) is None


# ---------------------------------------------------------------------------
# get_active_mbr
# ---------------------------------------------------------------------------

def test_get_active_mbr_none_when_no_active(db):
    _insert_mbr(db, produkt="Prod X", status="draft")
    assert get_active_mbr(db, "Prod X") is None


def test_get_active_mbr_returns_active(db):
    _insert_mbr(db, produkt="Prod X", status="archived")
    mbr_id = _insert_mbr(db, produkt="Prod X", wersja=2, status="active")
    result = get_active_mbr(db, "Prod X")
    assert result is not None
    assert result["mbr_id"] == mbr_id
    assert result["status"] == "active"


def test_get_active_mbr_none_for_unknown_product(db):
    assert get_active_mbr(db, "NonExistent") is None


# ---------------------------------------------------------------------------
# activate_mbr
# ---------------------------------------------------------------------------

def test_activate_mbr_sets_status_to_active(db):
    mbr_id = _insert_mbr(db, status="draft")
    ok = activate_mbr(db, mbr_id)
    assert ok is True
    row = get_mbr(db, mbr_id)
    assert row["status"] == "active"
    assert row["dt_aktywacji"] is not None


def test_activate_mbr_archives_previous_active(db):
    old_id = _insert_mbr(db, produkt="Prod Y", wersja=1, status="active")
    new_id = _insert_mbr(db, produkt="Prod Y", wersja=2, status="draft")
    ok = activate_mbr(db, new_id)
    assert ok is True
    assert get_mbr(db, old_id)["status"] == "archived"
    assert get_mbr(db, new_id)["status"] == "active"


def test_activate_mbr_rejects_non_draft(db):
    mbr_id = _insert_mbr(db, status="active")
    ok = activate_mbr(db, mbr_id)
    assert ok is False


def test_activate_mbr_nonexistent_returns_false(db):
    assert activate_mbr(db, 9999) is False


# ---------------------------------------------------------------------------
# clone_mbr
# ---------------------------------------------------------------------------

def test_clone_mbr_creates_draft_copy(db):
    src_id = _insert_mbr(db, produkt="Prod Z", wersja=1, etapy='["etap"]', parametry='{"key": 1}')
    new_id = clone_mbr(db, src_id, user="kloner")
    assert new_id is not None
    new_row = get_mbr(db, new_id)
    assert new_row["produkt"] == "Prod Z"
    assert new_row["status"] == "draft"
    assert new_row["etapy_json"] == '["etap"]'
    assert new_row["parametry_lab"] == '{"key": 1}'
    assert new_row["utworzony_przez"] == "kloner"


def test_clone_mbr_increments_version(db):
    _insert_mbr(db, produkt="Prod Z", wersja=1)
    _insert_mbr(db, produkt="Prod Z", wersja=2)
    src_id = _insert_mbr(db, produkt="Prod Z", wersja=3)
    new_id = clone_mbr(db, src_id, user="x")
    new_row = get_mbr(db, new_id)
    assert new_row["wersja"] == 4


def test_clone_mbr_nonexistent_returns_none(db):
    assert clone_mbr(db, 9999, user="x") is None
