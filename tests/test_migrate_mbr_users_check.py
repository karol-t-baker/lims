"""Regression: init_mbr_tables must not silently fail when rebuilding mbr_users
on a DB that already has the default_grupa column added by a later migration.

Reproduces the column-count mismatch: mbr_users exists with 6 cols, ddl lacks
'produkcja' — rebuild must preserve all 6 cols, not truncate to 5.
"""

import sqlite3
import pytest

from mbr.models import init_mbr_tables


def _make_legacy_mbr_users(db: sqlite3.Connection) -> None:
    """Simulate a DB captured before 'produkcja' was added to CHECK but
    AFTER default_grupa was added — the combination that triggers B2."""
    db.executescript("""
        CREATE TABLE mbr_users (
            user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            login           TEXT UNIQUE NOT NULL,
            password_hash   TEXT NOT NULL,
            rola            TEXT NOT NULL CHECK(rola IN ('technolog', 'lab', 'cert', 'kj', 'admin')),
            imie_nazwisko   TEXT,
            default_grupa   TEXT DEFAULT 'lab'
        );
        INSERT INTO mbr_users (login, password_hash, rola, imie_nazwisko, default_grupa)
        VALUES ('jan', 'h', 'lab', 'Jan Kowalski', 'lab');
    """)
    db.commit()


def test_init_preserves_default_grupa_when_expanding_role_check():
    """Rebuild must carry all existing columns over; default_grupa must survive."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    _make_legacy_mbr_users(db)

    init_mbr_tables(db)

    cols = [r["name"] for r in db.execute("PRAGMA table_info(mbr_users)").fetchall()]
    assert "default_grupa" in cols, (
        "default_grupa column was dropped during mbr_users CHECK rebuild"
    )

    row = db.execute(
        "SELECT login, rola, default_grupa FROM mbr_users WHERE login='jan'"
    ).fetchone()
    assert row["login"] == "jan"
    assert row["rola"] == "lab"
    assert row["default_grupa"] == "lab"


def test_init_expands_role_check_to_include_produkcja():
    """After init, inserting a produkcja user must succeed."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    _make_legacy_mbr_users(db)

    init_mbr_tables(db)

    db.execute(
        "INSERT INTO mbr_users (login, password_hash, rola, imie_nazwisko) "
        "VALUES ('op1', 'h', 'produkcja', 'Op One')"
    )
    row = db.execute("SELECT rola FROM mbr_users WHERE login='op1'").fetchone()
    assert row["rola"] == "produkcja"


def test_init_idempotent_on_fresh_db():
    """Fresh DB path still works (no legacy table to rebuild)."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_mbr_tables(db)
    init_mbr_tables(db)  # second call must be a no-op
    db.execute(
        "INSERT INTO mbr_users (login, password_hash, rola) VALUES ('t', 'h', 'produkcja')"
    )
