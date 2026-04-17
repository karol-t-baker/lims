"""PUT /api/cert/config/product/<key> atomicity + validation regressions.

Lock in the CE-1/CE-2 fixes: if the write phase fails for any reason,
the pre-existing cert rows must still be there after the response. The
old path deleted rows first, then raised NameError mid-INSERT, leaving
the product with an empty cert config.
"""

import json as _json
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
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (1, 'ph_test', 'pH', 'bezposredni')")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (2, 'nd20_test', 'nD20', 'bezposredni')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('TEST', 'Test')")
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) VALUES ('TEST', 'base', 'Test', '[]', 0)"
    )
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, variant_id) "
        "VALUES ('TEST', 1, 0, 'pH', NULL)"
    )
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, variant_id) "
        "VALUES ('TEST', 2, 1, 'nD20', NULL)"
    )
    db.commit()


def _admin_client(monkeypatch, db):
    import mbr.db
    import mbr.certs.routes
    import mbr.laborant.routes
    import mbr.technolog.routes
    import mbr.admin.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.certs.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.technolog.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.routes, "db_session", fake_db_session)
    # Skip the on-disk cert_config.json write during tests.
    from mbr.certs import generator as _gen
    monkeypatch.setattr(_gen, "save_cert_config_export", lambda db=None: None)
    import mbr.certs.routes as _cr
    monkeypatch.setattr(_cr, "save_cert_config_export", lambda db=None: None, raising=False)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": "admin", "worker_id": None}
    return client


def test_put_config_preserves_rows_when_add_param_mapping_fails(monkeypatch, db):
    """If a variant add_parameters entry references an unknown kod, the
    whole save is rejected and the original parametry_cert rows remain."""
    _seed(db)
    client = _admin_client(monkeypatch, db)

    before = db.execute(
        "SELECT COUNT(*) AS n FROM parametry_cert WHERE produkt='TEST' AND variant_id IS NULL"
    ).fetchone()["n"]
    assert before == 2

    resp = client.put(
        "/api/cert/config/product/TEST",
        json={
            "parameters": [
                {"id": "ph_test", "name_pl": "pH", "data_field": "ph_test"},
                {"id": "nd20_test", "name_pl": "nD20", "data_field": "nd20_test"},
            ],
            "variants": [
                {
                    "id": "base", "label": "Base", "flags": [],
                    "overrides": {
                        "add_parameters": [
                            {"id": "doesnotexist", "data_field": "doesnotexist", "name_pl": "X"},
                        ],
                    },
                },
            ],
        },
    )
    assert resp.status_code == 400
    # Validation must catch this BEFORE any DELETE runs.
    after = db.execute(
        "SELECT COUNT(*) AS n FROM parametry_cert WHERE produkt='TEST' AND variant_id IS NULL"
    ).fetchone()["n"]
    assert after == before, "base cert rows must survive a failed save"


def test_put_config_accepts_null_name_pl_as_warning_not_error(monkeypatch, db):
    _seed(db)
    # Insert a legacy row with NULL name_pl — shouldn't block the next save.
    db.execute(
        "UPDATE parametry_cert SET name_pl = NULL WHERE produkt='TEST' AND parametr_id=1"
    )
    db.commit()
    client = _admin_client(monkeypatch, db)

    resp = client.put(
        "/api/cert/config/product/TEST",
        json={
            "parameters": [
                {"id": "ph_test", "data_field": "ph_test"},  # no name_pl intentionally
                {"id": "nd20_test", "name_pl": "nD20", "data_field": "nd20_test"},
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert any("name" in w.lower() or "pl" in w.lower() for w in body.get("warnings", []))


def test_preview_rejects_oversized_payload(monkeypatch, db):
    client = _admin_client(monkeypatch, db)
    # 250 parameters > cap (200)
    product = {
        "parameters": [{"id": f"p{i}", "name_pl": "x"} for i in range(250)],
    }
    resp = client.post(
        "/api/cert/config/preview",
        json={"product": product, "variant_id": "base"},
    )
    assert resp.status_code == 400
    assert "parametr" in resp.get_json()["error"].lower()


def test_preview_rejects_oversized_string(monkeypatch, db):
    client = _admin_client(monkeypatch, db)
    product = {
        "parameters": [{"id": "p", "name_pl": "X" * 5000}],
    }
    resp = client.post(
        "/api/cert/config/preview",
        json={"product": product, "variant_id": "base"},
    )
    assert resp.status_code == 400


def test_delete_product_issued_count_preflight(monkeypatch, db):
    _seed(db)
    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia) VALUES (1, 'TEST', 1, '2026-01-01')")
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, typ) "
        "VALUES (1, 'B1', '1/2026', '2026-04-17', 'szarza')"
    )
    ebr_id = db.execute("SELECT ebr_id FROM ebr_batches LIMIT 1").fetchone()["ebr_id"]
    db.execute(
        "INSERT INTO swiadectwa (ebr_id, template_name, nr_partii, pdf_path, dt_wystawienia, wystawil) "
        "VALUES (?, 'Test base', '1/2026', '/p.pdf', '2026-04-17', 'tester')",
        (ebr_id,),
    )
    db.commit()
    client = _admin_client(monkeypatch, db)
    resp = client.get("/api/cert/config/product/TEST/issued-count")
    assert resp.status_code == 200
    assert resp.get_json()["count"] == 1
