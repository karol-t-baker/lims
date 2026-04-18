"""Tests for mbr.chzt — sessions, pomiary, autosave, history."""

import json as _json
import sqlite3
import pytest
from contextlib import contextmanager
from datetime import datetime, date

from mbr.models import init_mbr_tables
from mbr.chzt.models import init_chzt_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    init_chzt_tables(conn)
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (1, 'Jan', 'Kowalski', 'JK', 'JK', 1)"
    )
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (2, 'Anna', 'Nowak', 'AN', 'AN', 1)"
    )
    conn.commit()
    yield conn
    conn.close()


def test_init_chzt_tables_creates_sesje(db):
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chzt_sesje'"
    ).fetchone()
    assert row is not None


def test_init_chzt_tables_creates_pomiary(db):
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chzt_pomiary'"
    ).fetchone()
    assert row is not None


def test_init_chzt_tables_data_unique(db):
    db.execute(
        "INSERT INTO chzt_sesje (data, n_kontenery, created_at, created_by) "
        "VALUES ('2026-04-18', 8, '2026-04-18T10:00:00', 1)"
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO chzt_sesje (data, n_kontenery, created_at, created_by) "
            "VALUES ('2026-04-18', 8, '2026-04-18T11:00:00', 1)"
        )


def test_init_chzt_tables_pomiar_unique_per_session(db):
    db.execute(
        "INSERT INTO chzt_sesje (id, data, n_kontenery, created_at, created_by) "
        "VALUES (1, '2026-04-18', 8, '2026-04-18T10:00:00', 1)"
    )
    db.execute(
        "INSERT INTO chzt_pomiary (sesja_id, punkt_nazwa, kolejnosc, updated_at) "
        "VALUES (1, 'hala', 1, '2026-04-18T10:00:00')"
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO chzt_pomiary (sesja_id, punkt_nazwa, kolejnosc, updated_at) "
            "VALUES (1, 'hala', 2, '2026-04-18T10:05:00')"
        )
