"""/api/cert/generate honors target_produkt when an alias row exists."""

import json
import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


def _seed(db):
    db.execute("INSERT INTO produkty (nazwa, display_name, spec_number, expiry_months) "
               "VALUES ('K40GLOL', 'K40GLOL', 'SPEC-K', 12)")
    db.execute("INSERT INTO produkty (nazwa, display_name, spec_number, expiry_months) "
               "VALUES ('GLOL40', 'GLOL40', 'SPEC-G', 12)")
    db.execute("INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
               "VALUES ('K40GLOL', 'base', 'K40GLOL', '[]', 0)")
    db.execute("INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
               "VALUES ('GLOL40', 'base', 'GLOL40', '[]', 0)")
    db.execute("INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, dt_utworzenia) "
               "VALUES ('K40GLOL', 1, 'active', '[]', '{}', datetime('now'))")
    db.execute("INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, typ) "
               "VALUES (1, 'K40GLOL__1_2026', '1/2026', datetime('now'), 'completed', 'zbiornik')")
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
        sess["shift_workers"] = []
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


def _patch_pdf(monkeypatch):
    import mbr.certs.routes as routes_mod
    monkeypatch.setattr(routes_mod, "generate_certificate_pdf",
                        lambda *a, **kw: b"%PDF-1.4 fake")
    monkeypatch.setattr(routes_mod, "save_certificate_data",
                        lambda *a, **kw: None)


def test_generate_without_target_defaults_to_ebr_produkt(client, db, monkeypatch):
    _patch_pdf(monkeypatch)
    calls = []
    import mbr.certs.routes as routes_mod
    monkeypatch.setattr(routes_mod, "generate_certificate_pdf",
                        lambda produkt, *a, **kw: (calls.append(produkt), b"%PDF-1.4 fake")[1])

    r = client.post("/api/cert/generate", json={
        "ebr_id": 1, "variant_id": "base", "wystawil": "tester",
    })
    assert r.status_code == 200, r.data
    assert calls == ["K40GLOL"]
    row = db.execute("SELECT target_produkt FROM swiadectwa WHERE ebr_id=1").fetchone()
    assert row["target_produkt"] is None


def test_generate_with_aliased_target_uses_target(client, db, monkeypatch):
    _patch_pdf(monkeypatch)
    db.execute("INSERT INTO cert_alias VALUES ('K40GLOL', 'GLOL40')")
    db.commit()
    calls = []
    import mbr.certs.routes as routes_mod
    monkeypatch.setattr(routes_mod, "generate_certificate_pdf",
                        lambda produkt, *a, **kw: (calls.append(produkt), b"%PDF-1.4 fake")[1])

    r = client.post("/api/cert/generate", json={
        "ebr_id": 1, "variant_id": "base", "target_produkt": "GLOL40",
        "wystawil": "tester",
    })
    assert r.status_code == 200, r.data
    assert calls == ["GLOL40"]
    row = db.execute("SELECT target_produkt FROM swiadectwa WHERE ebr_id=1").fetchone()
    assert row["target_produkt"] == "GLOL40"


def test_generate_with_target_but_no_alias_returns_400(client, db, monkeypatch):
    _patch_pdf(monkeypatch)
    r = client.post("/api/cert/generate", json={
        "ebr_id": 1, "variant_id": "base", "target_produkt": "GLOL40",
        "wystawil": "tester",
    })
    assert r.status_code == 400
    body = r.get_json()
    assert "alias" in (body.get("error") or "").lower()


def test_generate_target_equals_ebr_produkt_is_always_allowed(client, db, monkeypatch):
    _patch_pdf(monkeypatch)
    r = client.post("/api/cert/generate", json={
        "ebr_id": 1, "variant_id": "base", "target_produkt": "K40GLOL",
        "wystawil": "tester",
    })
    assert r.status_code == 200, r.data


def test_regen_pdf_uses_target_produkt_when_present(client, db, monkeypatch):
    """/api/cert/<id>/pdf regenerates via target_produkt if the archive has one."""
    _patch_pdf(monkeypatch)
    db.execute("INSERT INTO cert_alias VALUES ('K40GLOL', 'GLOL40')")
    db.commit()

    # Issue an aliased cert so data_json stores target_produkt
    r = client.post("/api/cert/generate", json={
        "ebr_id": 1, "variant_id": "base", "target_produkt": "GLOL40",
        "wystawil": "tester",
    })
    assert r.status_code == 200
    cert_id = int(r.headers["X-Cert-Id"])

    # Now regenerate — spy on generate_certificate_pdf to see which produkt comes in
    calls = []
    import mbr.certs.routes as routes_mod
    monkeypatch.setattr(routes_mod, "generate_certificate_pdf",
                        lambda produkt, *a, **kw: (calls.append(produkt), b"%PDF-1.4 fake")[1])

    r = client.get(f"/api/cert/{cert_id}/pdf")
    assert r.status_code == 200
    assert calls == ["GLOL40"], f"expected target_produkt routing, got {calls}"


def test_regen_pdf_falls_back_to_produkt_for_legacy_rows(client, db, monkeypatch):
    """Archive entries from before target_produkt existed lack the key — must still work."""
    _patch_pdf(monkeypatch)

    # Issue a non-aliased cert — data_json has target_produkt=K40GLOL but we SIMULATE
    # a legacy row by manually deleting the key from data_json.
    r = client.post("/api/cert/generate", json={
        "ebr_id": 1, "variant_id": "base", "wystawil": "tester",
    })
    assert r.status_code == 200
    cert_id = int(r.headers["X-Cert-Id"])

    # Strip target_produkt from the archived data_json (legacy simulation)
    import json as _json
    row = db.execute("SELECT data_json FROM swiadectwa WHERE id=?", (cert_id,)).fetchone()
    gen = _json.loads(row["data_json"])
    gen.pop("target_produkt", None)
    db.execute("UPDATE swiadectwa SET data_json=? WHERE id=?",
               (_json.dumps(gen), cert_id))
    db.commit()

    calls = []
    import mbr.certs.routes as routes_mod
    monkeypatch.setattr(routes_mod, "generate_certificate_pdf",
                        lambda produkt, *a, **kw: (calls.append(produkt), b"%PDF-1.4 fake")[1])

    r = client.get(f"/api/cert/{cert_id}/pdf")
    assert r.status_code == 200
    assert calls == ["K40GLOL"], f"expected fallback to produkt, got {calls}"
