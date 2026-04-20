"""PR1: opisowe_wartosci column + CRUD + validation."""

import json as _json
import sqlite3
from contextlib import contextmanager

import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


@pytest.fixture
def client(monkeypatch, db):
    """Flask test client with db_session monkeypatched to shared in-memory db."""
    import mbr.db
    from mbr.app import app

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["user"] = {"username": "admin_test", "rola": "admin", "id": 1}
        yield c


def test_opisowe_wartosci_column_exists(db):
    """Schema migration adds opisowe_wartosci column to parametry_analityczne."""
    cols = [r[1] for r in db.execute("PRAGMA table_info(parametry_analityczne)")]
    assert "opisowe_wartosci" in cols
