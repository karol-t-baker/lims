"""Verify variant add_parameter override edits survive PUT→GET roundtrip.

Critical regression: pre-fix, frontend was sending stale legacy name_pl/name_en/method
for variant add_parameters, while the master-detail editor only updated *_override
fields. Edits were silently lost on save.
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
        "VALUES (2, 'avon', 'Av-on parameter', 'bezposredni', 'Av-on EN', 'PN-Av-on')"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('TEST', 'Test')")
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
        "VALUES ('TEST', 'base', 'Base', '[]', 0)"
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


def test_variant_add_param_override_survives_save(monkeypatch, db):
    """Edit name_pl override on a variant add_parameter, save, reload — value persists."""
    _seed(db)
    client = _admin_client(monkeypatch, db)

    # Initial save: create base param + LV variant with one add_param using nd20.
    payload = {
        "display_name": "Test",
        "spec_number": "P000",
        "expiry_months": 12,
        "opinion_pl": "OK",
        "opinion_en": "OK",
        "parameters": [
            {"id": "nd20", "data_field": "nd20", "kolejnosc": 0,
             "name_pl": None, "name_en": None, "method": None,
             "requirement": "1.45", "format": "4", "qualitative_result": None},
        ],
        "variants": [
            {"id": "base", "label": "Base", "flags": [], "kolejnosc": 0, "overrides": {}},
            {"id": "lv", "label": "LV", "flags": [], "kolejnosc": 1, "overrides": {
                "add_parameters": [
                    # PRE-FIX SHAPE — stale legacy name_pl set to registry value at row creation:
                    {"id": "avon", "data_field": "avon",
                     "name_pl": "Custom Av-on PL",
                     "name_en": None, "method": None,
                     "requirement": "10", "format": "2", "qualitative_result": None},
                ]
            }},
        ],
    }
    rv = client.put("/api/cert/config/product/TEST", json=payload)
    assert rv.status_code == 200, rv.get_json()

    # Read back — verify the custom override survived.
    rv = client.get("/api/cert/config/product/TEST")
    assert rv.status_code == 200
    j = rv.get_json()
    variants = j["product"]["variants"]
    lv = next(v for v in variants if v["id"] == "lv")
    aps = lv["overrides"]["add_parameters"]
    assert len(aps) == 1
    ap = aps[0]
    assert ap["name_pl_override"] == "Custom Av-on PL"
    assert ap["name_pl"] == "Custom Av-on PL"  # effective
    # Inheriting fields fall back to registry
    assert ap["name_en_override"] is None
    assert ap["name_en"] == "Av-on EN"  # registry value
    assert ap["method_override"] is None
    assert ap["method"] == "PN-Av-on"  # registry value


def test_variant_add_param_null_override_clears(monkeypatch, db):
    """Frontend sends null override → server stores NULL → cert generator falls back to registry."""
    _seed(db)
    client = _admin_client(monkeypatch, db)

    payload = {
        "display_name": "Test",
        "expiry_months": 12,
        "opinion_pl": "", "opinion_en": "",
        "parameters": [],
        "variants": [
            {"id": "base", "label": "Base", "flags": [], "kolejnosc": 0, "overrides": {}},
            {"id": "lv", "label": "LV", "flags": [], "kolejnosc": 1, "overrides": {
                "add_parameters": [
                    {"id": "avon", "data_field": "avon",
                     "name_pl": None, "name_en": None, "method": None,
                     "requirement": "", "format": "1", "qualitative_result": None},
                ]
            }},
        ],
    }
    rv = client.put("/api/cert/config/product/TEST", json=payload)
    assert rv.status_code == 200

    # DB row should have NULLs
    row = db.execute(
        "SELECT name_pl, name_en, method FROM parametry_cert "
        "WHERE produkt='TEST' AND variant_id IS NOT NULL"
    ).fetchone()
    assert row["name_pl"] is None
    assert row["name_en"] is None
    assert row["method"] is None
