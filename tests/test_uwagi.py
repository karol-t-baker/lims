"""Tests for uwagi_koncowe (final batch notes) feature."""

import sqlite3
from datetime import datetime

import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    try:
        conn.execute("ALTER TABLE ebr_batches ADD COLUMN nr_zbiornika TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass
    yield conn
    conn.close()


@pytest.fixture
def ebr_batch(db):
    """Creates a minimal MBR template + open EBR batch, returns ebr_id."""
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia) VALUES (?, 1, 'active', '[]', '{}', 'test', ?)",
        ("TestProduct", now),
    )
    mbr_id = db.execute(
        "SELECT mbr_id FROM mbr_templates WHERE produkt='TestProduct'"
    ).fetchone()["mbr_id"]
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, typ) "
        "VALUES (?, ?, ?, ?, 'open', 'szarza')",
        (mbr_id, "TestProduct__1", "1/2026", now),
    )
    db.commit()
    return db.execute(
        "SELECT ebr_id FROM ebr_batches WHERE batch_id='TestProduct__1'"
    ).fetchone()["ebr_id"]


def test_schema_has_uwagi_koncowe_column(db):
    """Regression test: ebr_batches must have uwagi_koncowe column after init."""
    cols = [r["name"] for r in db.execute("PRAGMA table_info(ebr_batches)").fetchall()]
    assert "uwagi_koncowe" in cols


def test_schema_has_history_table(db):
    """Regression test: ebr_uwagi_history table must exist."""
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ebr_uwagi_history'"
    ).fetchall()
    assert len(rows) == 1
