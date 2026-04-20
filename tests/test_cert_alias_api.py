"""Admin CRUD for cert_alias: GET / POST / DELETE /api/cert/aliases."""

import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


def _seed(db):
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('K40GLOL', 'K40GLOL')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('GLOL40', 'GLOL40')")
    db.commit()


def _make_client(monkeypatch, db, rola="admin"):
    import mbr.db
    import mbr.certs.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.certs.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": rola, "worker_id": None}
    return c


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    _seed(conn)
    yield conn
    conn.close()


@pytest.fixture
def admin_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="admin")


@pytest.fixture
def lab_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="lab")


def test_post_alias_persists(admin_client, db):
    r = admin_client.post("/api/cert/aliases", json={
        "source_produkt": "K40GLOL", "target_produkt": "GLOL40",
    })
    assert r.status_code == 200, r.get_json()
    row = db.execute(
        "SELECT * FROM cert_alias WHERE source_produkt='K40GLOL' AND target_produkt='GLOL40'"
    ).fetchone()
    assert row is not None


def test_post_alias_rejects_self(admin_client):
    r = admin_client.post("/api/cert/aliases", json={
        "source_produkt": "K40GLOL", "target_produkt": "K40GLOL",
    })
    assert r.status_code == 400
    assert "self" in (r.get_json().get("error") or "").lower()


def test_post_alias_rejects_unknown_target(admin_client):
    r = admin_client.post("/api/cert/aliases", json={
        "source_produkt": "K40GLOL", "target_produkt": "NONEXISTENT",
    })
    assert r.status_code == 404
    assert "target" in (r.get_json().get("error") or "").lower()


def test_post_alias_duplicate_is_idempotent(admin_client, db):
    admin_client.post("/api/cert/aliases", json={
        "source_produkt": "K40GLOL", "target_produkt": "GLOL40",
    })
    r = admin_client.post("/api/cert/aliases", json={
        "source_produkt": "K40GLOL", "target_produkt": "GLOL40",
    })
    assert r.status_code == 200
    count = db.execute(
        "SELECT COUNT(*) FROM cert_alias WHERE source_produkt='K40GLOL' AND target_produkt='GLOL40'"
    ).fetchone()[0]
    assert count == 1


def test_get_aliases_returns_all(admin_client, db):
    db.execute("INSERT INTO cert_alias VALUES ('K40GLOL', 'GLOL40')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('K7', 'K7')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('K7B', 'K7B')")
    db.execute("INSERT INTO cert_alias VALUES ('K7', 'K7B')")
    db.commit()
    r = admin_client.get("/api/cert/aliases")
    data = r.get_json()
    pairs = sorted((a["source_produkt"], a["target_produkt"]) for a in data["aliases"])
    assert pairs == [("K40GLOL", "GLOL40"), ("K7", "K7B")]


def test_delete_alias_removes(admin_client, db):
    db.execute("INSERT INTO cert_alias VALUES ('K40GLOL', 'GLOL40')")
    db.commit()
    r = admin_client.delete("/api/cert/aliases/K40GLOL/GLOL40")
    assert r.status_code == 200
    row = db.execute(
        "SELECT * FROM cert_alias WHERE source_produkt='K40GLOL'"
    ).fetchone()
    assert row is None


def test_delete_nonexistent_alias_is_idempotent(admin_client):
    r = admin_client.delete("/api/cert/aliases/K40GLOL/GLOL40")
    assert r.status_code == 200


def test_post_alias_requires_admin(lab_client):
    r = lab_client.post("/api/cert/aliases", json={
        "source_produkt": "K40GLOL", "target_produkt": "GLOL40",
    })
    assert r.status_code == 403
