"""tests/test_sync.py — Tests for index-based sync."""

import sqlite3
from unittest.mock import patch

import pytest

from mbr.db import get_db
from mbr.models import init_mbr_tables


@pytest.fixture
def db(tmp_path):
    """Fresh in-memory-like DB with all MBR tables."""
    db_path = tmp_path / "test.sqlite"
    with patch("mbr.db.DB_PATH", db_path):
        conn = get_db()
        init_mbr_tables(conn)
        yield conn
        conn.close()


def test_sync_seq_column_exists(db):
    """ebr_batches has sync_seq INTEGER column after init."""
    cols = {r[1]: r[2] for r in db.execute("PRAGMA table_info(ebr_batches)").fetchall()}
    assert "sync_seq" in cols
    assert cols["sync_seq"] == "INTEGER"
