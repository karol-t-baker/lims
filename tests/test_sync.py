"""tests/test_sync.py — Tests for index-based sync."""

import sqlite3
from unittest.mock import patch

import pytest

from mbr.db import get_db
from mbr.models import init_mbr_tables
from mbr.laborant.models import complete_ebr


@pytest.fixture
def db(tmp_path):
    """Fresh in-memory-like DB with all MBR tables."""
    db_path = tmp_path / "test.sqlite"
    with patch("mbr.db.DB_PATH", db_path):
        conn = get_db()
        init_mbr_tables(conn)
        yield conn
        conn.close()


def _create_batch(db, batch_id="TEST__1_2026", nr_partii="1/2026", mbr_id=1):
    """Helper: create an open batch, return ebr_id."""
    db.execute(
        "INSERT OR IGNORE INTO mbr_templates (mbr_id, produkt, wersja, status, parametry_lab, dt_utworzenia) VALUES (?,?,?,?,?,datetime('now'))",
        (mbr_id, "Test", 1, "active", "{}"),
    )
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status) VALUES (?,?,?,datetime('now'),'open')",
        (mbr_id, batch_id, nr_partii),
    )
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_complete_ebr_assigns_sync_seq(db):
    """Completing a batch assigns a monotonically increasing sync_seq."""
    id1 = _create_batch(db, "A__1", "1/2026")
    id2 = _create_batch(db, "B__2", "2/2026")

    complete_ebr(db, id1)
    complete_ebr(db, id2)

    seq1 = db.execute("SELECT sync_seq FROM ebr_batches WHERE ebr_id=?", (id1,)).fetchone()[0]
    seq2 = db.execute("SELECT sync_seq FROM ebr_batches WHERE ebr_id=?", (id2,)).fetchone()[0]

    assert seq1 is not None
    assert seq2 is not None
    assert seq2 > seq1


def test_sync_seq_column_exists(db):
    """ebr_batches has sync_seq INTEGER column after init."""
    cols = {r[1]: r[2] for r in db.execute("PRAGMA table_info(ebr_batches)").fetchall()}
    assert "sync_seq" in cols
    assert cols["sync_seq"] == "INTEGER"
