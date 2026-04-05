"""
test_db.py — Tests for mbr/db.py connection helpers.
"""

import sqlite3
from unittest.mock import patch
from pathlib import Path

import pytest

from mbr.db import get_db, db_session


def test_get_db_returns_row_factory(tmp_path):
    """get_db() returns a connection with sqlite3.Row factory set."""
    fake_db = tmp_path / "test.sqlite"
    with patch("mbr.db.DB_PATH", fake_db):
        conn = get_db()
        try:
            assert conn.row_factory is sqlite3.Row
        finally:
            conn.close()


def test_get_db_foreign_keys_on(tmp_path):
    """get_db() enables foreign_keys pragma."""
    fake_db = tmp_path / "test.sqlite"
    with patch("mbr.db.DB_PATH", fake_db):
        conn = get_db()
        try:
            result = conn.execute("PRAGMA foreign_keys").fetchone()
            assert result[0] == 1
        finally:
            conn.close()


def test_db_session_yields_connection(tmp_path):
    """db_session() context manager yields a usable sqlite3 connection."""
    fake_db = tmp_path / "test.sqlite"
    with patch("mbr.db.DB_PATH", fake_db):
        with db_session() as conn:
            assert isinstance(conn, sqlite3.Connection)
            # Connection must be usable
            result = conn.execute("SELECT 1").fetchone()
            assert result[0] == 1


def test_db_session_connection_has_row_factory(tmp_path):
    """db_session() yields a connection with Row factory."""
    fake_db = tmp_path / "test.sqlite"
    with patch("mbr.db.DB_PATH", fake_db):
        with db_session() as conn:
            assert conn.row_factory is sqlite3.Row


def test_db_session_closes_connection(tmp_path):
    """db_session() closes the connection after exiting."""
    fake_db = tmp_path / "test.sqlite"
    captured = {}
    with patch("mbr.db.DB_PATH", fake_db):
        with db_session() as conn:
            captured["conn"] = conn
    # After context exit, executing on the connection should raise
    with pytest.raises(Exception):
        captured["conn"].execute("SELECT 1")


def test_db_session_closes_on_exception(tmp_path):
    """db_session() closes the connection even when an exception is raised."""
    fake_db = tmp_path / "test.sqlite"
    captured = {}
    with patch("mbr.db.DB_PATH", fake_db):
        with pytest.raises(ValueError):
            with db_session() as conn:
                captured["conn"] = conn
                raise ValueError("test error")
    with pytest.raises(Exception):
        captured["conn"].execute("SELECT 1")
