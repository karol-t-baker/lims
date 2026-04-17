"""Tests for /api/bindings/* — SSOT endpoints for produkt_etap_limity CRUD."""

import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    _seed_bindings_fixture(conn)
    yield conn
    conn.close()


def _seed_bindings_fixture(db):
    db.execute("DELETE FROM parametry_analityczne")
    db.executemany(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision, aktywny) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        [(1, "ph", "pH", "bezposredni", 2),
         (2, "dea", "DEA", "bezposredni", 2)],
    )
    db.execute(
        "INSERT OR IGNORE INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
        "VALUES (6, 'analiza_koncowa', 'Analiza końcowa', 'jednorazowy')"
    )
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('TEST_P', 6, 1)")
    db.execute(
        "INSERT INTO produkt_etap_limity "
        "(produkt, etap_id, parametr_id, min_limit, max_limit, precision, kolejnosc, "
        " dla_szarzy, dla_zbiornika, dla_platkowania, grupa) "
        "VALUES ('TEST_P', 6, 1, 0, 11, 2, 1, 1, 1, 0, 'lab')"
    )
    db.commit()


def _make_client(monkeypatch, db, rola="admin"):
    """Build a Flask test client with the in-memory db monkey-patched in.
    Pattern lifted from tests/test_admin_audit.py."""
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

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": rola, "worker_id": None}
    return client


@pytest.fixture
def client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="admin")


# ---------------------------------------------------------------------------
# GET /api/bindings
# ---------------------------------------------------------------------------

def test_get_bindings_returns_list(client):
    resp = client.get("/api/bindings?produkt=TEST_P&etap_id=6")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert len(data) == 1
    b = data[0]
    assert b["produkt"] == "TEST_P"
    assert b["etap_id"] == 6
    assert b["parametr_id"] == 1
    assert b["kod"] == "ph"
    assert b["min_limit"] == 0
    assert b["max_limit"] == 11
    assert b["dla_szarzy"] == 1
    assert b["dla_zbiornika"] == 1
    assert b["dla_platkowania"] == 0


def test_get_bindings_accepts_etap_kod_instead_of_id(client):
    resp = client.get("/api/bindings?produkt=TEST_P&etap_kod=analiza_koncowa")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["etap_id"] == 6


def test_get_bindings_empty_for_unknown_produkt(client):
    resp = client.get("/api/bindings?produkt=NO_SUCH&etap_id=6")
    assert resp.status_code == 200
    assert resp.get_json() == []
