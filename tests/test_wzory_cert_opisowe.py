"""PR1: PUT /api/cert/config/product/<key> validates qualitative_result for jakosciowy params."""

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
    import mbr.db
    import mbr.certs.routes
    from mbr.app import app

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.certs.routes, "db_session", fake_db_session)
    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["user"] = {"login": "admin_test", "rola": "admin", "worker_id": None}
        yield c


def _seed_jakosciowy_param_on_product(db, produkt="TESTPROD", kod="zapach",
                                      wartosci=None):
    wartosci = wartosci or ["charakterystyczny", "obcy"]
    pid = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision, opisowe_wartosci) "
        "VALUES (?, ?, 'jakosciowy', 'lab', 0, ?)",
        (kod, kod.capitalize(), _json.dumps(wartosci)),
    ).lastrowid
    db.execute(
        "INSERT INTO produkty (nazwa, display_name) VALUES (?, ?)",
        (produkt, produkt),
    )
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label) VALUES (?, 'base', 'Base')",
        (produkt,),
    )
    db.commit()
    return pid, kod


def _base_payload(kod, qr):
    return {
        "parameters": [
            {"id": kod, "data_field": kod, "qualitative_result": qr,
             "requirement": "charakterystyczny", "format": "1",
             "name_pl": "Zapach", "name_en": "Odour"}
        ],
        "variants": [],
    }


def test_put_accepts_qualitative_result_from_allowed_list(client, db):
    _, kod = _seed_jakosciowy_param_on_product(db)
    r = client.put(f"/api/cert/config/product/TESTPROD", json=_base_payload(kod, "obcy"))
    assert r.status_code == 200, r.get_json()


def test_put_rejects_qualitative_result_outside_allowed_list(client, db):
    _, kod = _seed_jakosciowy_param_on_product(db)
    r = client.put(f"/api/cert/config/product/TESTPROD", json=_base_payload(kod, "invalid_value"))
    assert r.status_code == 400
    err = (r.get_json() or {}).get("error", "").lower()
    assert "niedozwolona" in err or "opisowe_wartosci" in err


def test_put_allows_empty_qualitative_result_for_jakosciowy(client, db):
    _, kod = _seed_jakosciowy_param_on_product(db)
    r = client.put(f"/api/cert/config/product/TESTPROD", json=_base_payload(kod, ""))
    assert r.status_code == 200


def test_put_validates_qualitative_result_in_variant_add_parameters(client, db):
    _, kod = _seed_jakosciowy_param_on_product(db)
    payload = {
        "parameters": [],
        "variants": [
            {"id": "base", "label": "Base", "overrides": {
                "remove_parameters": [],
                "add_parameters": [
                    {"id": kod, "data_field": kod, "qualitative_result": "invalid_value",
                     "requirement": "x", "format": "1"}
                ],
            }}
        ],
    }
    r = client.put("/api/cert/config/product/TESTPROD", json=payload)
    assert r.status_code == 400


def test_put_skips_validation_for_non_jakosciowy(client, db):
    """Non-jakosciowy params accept any qualitative_result text (backward compat)."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision) "
        "VALUES ('dens', 'Gęstość', 'bezposredni', 'lab', 2)"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('TP2', 'TP2')")
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label) VALUES ('TP2', 'base', 'Base')"
    )
    db.commit()
    payload = {
        "parameters": [
            {"id": "dens", "data_field": "dens", "qualitative_result": "anything goes",
             "requirement": "0.98-1.02", "format": "2"}
        ],
        "variants": [],
    }
    r = client.put("/api/cert/config/product/TP2", json=payload)
    assert r.status_code == 200
