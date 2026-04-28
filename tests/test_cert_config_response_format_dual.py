"""GET /api/cert/config/product/<key> exposes format_global + format_override."""
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


def _seed(db):
    db.execute("DELETE FROM parametry_analityczne")
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision) "
        "VALUES (1, 'nd20', 'nD20', 'bezposredni', 4)"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('TEST', 'Test')")
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) VALUES ('TEST', 'base', 'Base', '[]', 0)"
    )
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, format, variant_id) "
        "VALUES ('TEST', 1, 0, '2', NULL)"
    )
    db.commit()


def _admin_client(monkeypatch, db):
    import mbr.db, mbr.certs.routes, mbr.parametry.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.certs.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.parametry.routes, "db_session", fake_db_session)

    from mbr.app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "admin", "rola": "admin"}
    return client


def test_cert_config_get_includes_format_dual_fields(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.get("/api/cert/config/product/TEST")
    assert rv.status_code == 200
    j = rv.get_json()
    p = j["product"]["parameters"][0]
    assert p["format_global"] == "4"  # registry precision
    assert p["format_override"] == "2"  # cert config override
    assert p["format"] == "2"  # legacy effective preserved
