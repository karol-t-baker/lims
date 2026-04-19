"""Tests for grupa field on /api/parametry endpoints."""

import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _make_client(monkeypatch, db, rola="admin"):
    import mbr.db
    import mbr.parametry.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.parametry.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": rola, "worker_id": None}
    return c


@pytest.fixture
def client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="admin")


def test_post_parametry_with_grupa_zewn_persists(client, db):
    r = client.post("/api/parametry", json={
        "kod": "tpc", "label": "Total plate count", "typ": "bezposredni", "grupa": "zewn",
    })
    assert r.status_code == 200, r.get_json()
    row = db.execute("SELECT grupa FROM parametry_analityczne WHERE kod='tpc'").fetchone()
    assert row["grupa"] == "zewn"


def test_post_parametry_without_grupa_defaults_lab(client, db):
    r = client.post("/api/parametry", json={"kod": "x", "label": "X", "typ": "bezposredni"})
    assert r.status_code == 200
    row = db.execute("SELECT grupa FROM parametry_analityczne WHERE kod='x'").fetchone()
    assert row["grupa"] == "lab"


def test_post_parametry_rejects_unknown_grupa(client, db):
    r = client.post("/api/parametry", json={
        "kod": "x", "label": "X", "typ": "bezposredni", "grupa": "mikrobio",
    })
    assert r.status_code == 400
    assert "grupa" in (r.get_json().get("error") or "").lower()
    # Must not have created the row
    assert db.execute("SELECT COUNT(*) FROM parametry_analityczne WHERE kod='x'").fetchone()[0] == 0
