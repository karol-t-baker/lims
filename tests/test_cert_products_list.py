"""GET /api/cert/config/products surfaces produkty.aktywny per row.

Frontend (admin/wzory_cert.html) hides archived products by default and only
shows them after toggling "Pokaż archiwalne". The API must therefore return
the flag for every product so the client can filter without a second roundtrip.
"""
import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed_two_products(db):
    db.execute("INSERT INTO produkty (nazwa, display_name, aktywny) VALUES ('LIVE', 'Live Product', 1)")
    db.execute("INSERT INTO produkty (nazwa, display_name, aktywny) VALUES ('ARCH', 'Archived Product', 0)")
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
        "VALUES ('LIVE', 'base', 'Base', '[]', 0)"
    )
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
        "VALUES ('ARCH', 'base', 'Base', '[]', 0)"
    )
    db.commit()


def _admin_client(monkeypatch, db):
    import mbr.db
    import mbr.certs.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.certs.routes, "db_session", fake_db_session)

    from mbr.app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "admin", "rola": "admin"}
    return client


def test_products_list_returns_aktywny_flag_for_each_row(monkeypatch, db):
    _seed_two_products(db)
    client = _admin_client(monkeypatch, db)

    rv = client.get("/api/cert/config/products")
    assert rv.status_code == 200
    j = rv.get_json()
    assert j["ok"] is True

    by_key = {p["key"]: p for p in j["products"]}
    assert by_key["LIVE"]["aktywny"] == 1
    assert by_key["ARCH"]["aktywny"] == 0
