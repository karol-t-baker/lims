"""/api/cert/templates returns union of own + aliased variants."""

import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


def _seed(db):
    # Two products, each with their own cert variants
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('K40GLOL', 'K40GLOL')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('GLOL40', 'GLOL40')")
    db.execute("INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
               "VALUES ('K40GLOL', 'base', 'K40GLOL base', '[]', 0)")
    db.execute("INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
               "VALUES ('K40GLOL', 'loreal', 'K40GLOL — Loreal', '[]', 1)")
    db.execute("INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
               "VALUES ('GLOL40', 'base', 'GLOL40 base', '[]', 0)")
    db.execute("INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
               "VALUES ('GLOL40', 'mb', 'GLOL40 — MB', '[]', 1)")
    db.commit()


def _make_client(monkeypatch, db, rola="lab"):
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
def client(monkeypatch, db):
    return _make_client(monkeypatch, db)


def test_templates_no_alias_returns_only_own(client, db):
    r = client.get("/api/cert/templates?produkt=K40GLOL")
    data = r.get_json()
    templates = data["templates"]
    owners = sorted(set(t.get("owner_produkt") for t in templates))
    labels = sorted(t["display"] for t in templates)
    assert owners == ["K40GLOL"]
    assert labels == ["K40GLOL base", "K40GLOL — Loreal"]


def test_templates_with_alias_returns_union(client, db):
    db.execute("INSERT INTO cert_alias VALUES ('K40GLOL', 'GLOL40')")
    db.commit()
    r = client.get("/api/cert/templates?produkt=K40GLOL")
    data = r.get_json()
    templates = data["templates"]
    owners = sorted(set(t.get("owner_produkt") for t in templates))
    labels = sorted(t["display"] for t in templates)
    assert owners == ["GLOL40", "K40GLOL"]
    assert labels == ["GLOL40 base", "GLOL40 — MB",
                      "K40GLOL base", "K40GLOL — Loreal"]
    # Every template must carry owner_produkt
    for t in templates:
        assert "owner_produkt" in t
        assert t["owner_produkt"] in ("K40GLOL", "GLOL40")


def test_templates_empty_produkt_returns_empty(client):
    r = client.get("/api/cert/templates?produkt=")
    assert r.get_json() == {"templates": []}
