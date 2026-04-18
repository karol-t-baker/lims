"""Tests for /api/parametry/available — full registry with in_mbr flag."""
import json
import sqlite3
import pytest
from contextlib import contextmanager
from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    """In-memory SQLite DB with schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _make_client(monkeypatch, db):
    """Build a Flask test client with the in-memory db monkey-patched in."""
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
        sess["user"] = {"login": "tester", "rola": "admin", "worker_id": None}
    return client


@pytest.fixture
def client(monkeypatch, db):
    return _make_client(monkeypatch, db)


def test_available_without_produkt_returns_full_registry(client, db):
    """Legacy behavior — no produkt arg → all active params as plain list."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, skrot, typ, aktywny) "
        "VALUES ('ph', 'pH', 'pH', 'chem', 1)"
    )
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, skrot, typ, aktywny) "
        "VALUES ('lepkosc', 'Lepkość', 'LV', 'chem', 1)"
    )
    db.commit()

    r = client.get("/api/parametry/available")
    assert r.status_code == 200
    data = r.get_json()
    # No produkt → legacy shape: plain list
    assert isinstance(data, list)
    kods = {p["kod"] for p in data}
    assert "ph" in kods and "lepkosc" in kods


def test_available_with_produkt_no_mbr_returns_full_registry_with_flag(client, db):
    """Product with no active MBR → still full registry, all in_mbr=False, no_mbr=True."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, skrot, typ, aktywny) "
        "VALUES ('ph', 'pH', 'pH', 'chem', 1)"
    )
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, skrot, typ, aktywny) "
        "VALUES ('lepkosc', 'Lepkość', 'LV', 'chem', 1)"
    )
    db.commit()

    r = client.get("/api/parametry/available?produkt=NoMBR_Product")
    assert r.status_code == 200
    data = r.get_json()
    assert data["no_mbr"] is True
    assert data["produkt"] == "NoMBR_Product"
    # Full registry despite no MBR
    kods = {p["kod"] for p in data["params"]}
    assert "ph" in kods and "lepkosc" in kods
    # All flagged out-of-MBR
    for p in data["params"]:
        assert p["in_mbr"] is False


def test_available_with_produkt_in_mbr_flag_per_row(client, db):
    """With active MBR, each param in response has correct in_mbr flag."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, skrot, typ, aktywny) "
        "VALUES ('ph', 'pH', 'pH', 'chem', 1)"
    )
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, skrot, typ, aktywny) "
        "VALUES ('lepkosc', 'Lepkość', 'LV', 'chem', 1)"
    )
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, skrot, typ, aktywny) "
        "VALUES ('zapach', 'Zapach', 'ZP', 'kvalitativ', 1)"
    )
    # MBR analiza_koncowa includes only ph and lepkosc
    parametry_lab = {
        "analiza_koncowa": {
            "pola": [{"kod": "ph"}, {"kod": "lepkosc"}],
        },
    }
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, dt_utworzenia) "
        "VALUES (?, 1, 'active', '[]', ?, datetime('now'))",
        ("WithMBR_Product", json.dumps(parametry_lab)),
    )
    db.commit()

    r = client.get("/api/parametry/available?produkt=WithMBR_Product")
    assert r.status_code == 200
    data = r.get_json()
    assert data["no_mbr"] is False
    params_by_kod = {p["kod"]: p for p in data["params"]}
    assert params_by_kod["ph"]["in_mbr"] is True
    assert params_by_kod["lepkosc"]["in_mbr"] is True
    assert params_by_kod["zapach"]["in_mbr"] is False
