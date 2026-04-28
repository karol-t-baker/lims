"""GET /api/cert/config/product/<key> exposes *_global and *_override fields.

Task A4 of the Cert Editor Redesign plan: the editor frontend needs to render
two columns ("Globalne" vs "Override per-produkt"), so the cert config response
must surface both global registry values and raw per-product overrides for
every parameter — not just the legacy effective fields.

This test pins the JSON shape so future refactors (or a switch to using
get_cert_params() under the hood) can't silently drop the new fields.
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


def _seed(db):
    db.execute("DELETE FROM parametry_analityczne")
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, name_en, method_code) "
        "VALUES (1, 'nd20', 'Wsp. załamania', 'bezposredni', 'Refractive index', 'PN-EN ISO 5661')"
    )
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, name_en, method_code) "
        "VALUES (2, 'lk', 'Liczba kwasowa', 'bezposredni', 'Acid value', 'PN-EN ISO 660')"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('TEST', 'Test')")
    db.execute(
        "INSERT INTO cert_variants (id, produkt, variant_id, label, flags, kolejnosc) "
        "VALUES (10, 'TEST', 'base', 'Base', '[]', 0)"
    )
    # Base param row 1: name_en overridden, name_pl + method NULL (inherit)
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('TEST', 1, 0, NULL, 'Refractive index custom', NULL, NULL)"
    )
    # Base param row 2: all NULL (full inherit)
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('TEST', 2, 1, NULL, NULL, NULL, NULL)"
    )
    db.commit()


def _admin_client(monkeypatch, db):
    import mbr.db
    import mbr.certs.routes
    import mbr.parametry.routes

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


def test_cert_config_get_returns_dual_fields(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.get("/api/cert/config/product/TEST")
    assert rv.status_code == 200
    j = rv.get_json()
    assert j["ok"] is True
    params = j["product"]["parameters"]
    assert len(params) == 2

    # Param 0: name_en overridden, others inherit
    p0 = params[0]
    assert p0["name_pl_global"] == "Wsp. załamania"
    assert p0["name_en_global"] == "Refractive index"
    assert p0["method_global"] == "PN-EN ISO 5661"
    assert p0["name_pl_override"] is None
    assert p0["name_en_override"] == "Refractive index custom"
    assert p0["method_override"] is None

    # Legacy effective fields still present (don't break existing consumers)
    assert p0["name_pl"] == "Wsp. załamania"
    assert p0["name_en"] == "Refractive index custom"
    assert p0["method"] == "PN-EN ISO 5661"

    # Param 1: full inherit
    p1 = params[1]
    assert p1["name_pl_global"] == "Liczba kwasowa"
    assert p1["name_en_global"] == "Acid value"
    assert p1["method_global"] == "PN-EN ISO 660"
    assert p1["name_pl_override"] is None
    assert p1["name_en_override"] is None
    assert p1["method_override"] is None


def test_cert_config_get_variant_add_parameters_dual_fields(monkeypatch, db):
    """Variant add_parameters must expose dual fields too (editor renders the
    same two-column UI for variant-specific params)."""
    _seed(db)
    # Add a non-base variant with an add_parameter that overrides name_pl.
    db.execute(
        "INSERT INTO cert_variants (id, produkt, variant_id, label, flags, kolejnosc) "
        "VALUES (11, 'TEST', 'lv', 'LV', '[]', 1)"
    )
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('TEST', 1, 0, 'Variant nazwa', NULL, NULL, 11)"
    )
    db.commit()

    client = _admin_client(monkeypatch, db)
    rv = client.get("/api/cert/config/product/TEST")
    assert rv.status_code == 200
    j = rv.get_json()

    # Find the LV variant
    lv = next(v for v in j["product"]["variants"] if v["id"] == "lv")
    add_params = lv["overrides"]["add_parameters"]
    assert len(add_params) == 1
    ap = add_params[0]
    assert ap["name_pl_global"] == "Wsp. załamania"
    assert ap["name_pl_override"] == "Variant nazwa"
    assert ap["name_en_global"] == "Refractive index"
    assert ap["name_en_override"] is None
    assert ap["method_global"] == "PN-EN ISO 5661"
    assert ap["method_override"] is None
    # Legacy effective name_pl still respects override
    assert ap["name_pl"] == "Variant nazwa"
