"""PUT /api/parametry/<id>/formula-override — set/clear per-binding formula override."""
import json
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
        "INSERT INTO parametry_analityczne (id, kod, label, typ, formula) "
        "VALUES (1, 'sa', 'Substancja aktywna', 'obliczeniowy', 'sm - nacl - sa_bias')"
    )
    db.execute("INSERT OR IGNORE INTO produkty (nazwa, display_name) VALUES ('Cheminox_K', 'Cheminox K')")
    db.execute("INSERT OR IGNORE INTO produkty (nazwa, display_name) VALUES ('Other', 'Other')")
    db.execute(
        "INSERT INTO parametry_etapy (id, parametr_id, produkt, kontekst, kolejnosc, sa_bias) "
        "VALUES (10, 1, 'Cheminox_K', 'analiza_koncowa', 0, 0.6)"
    )
    db.execute(
        "INSERT INTO parametry_etapy (id, parametr_id, produkt, kontekst, kolejnosc) "
        "VALUES (11, 1, 'Other', 'sulfonowanie', 0)"
    )
    db.commit()


def _admin_client(monkeypatch, db):
    import mbr.db, mbr.parametry.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.parametry.routes, "db_session", fake_db_session)

    from mbr.app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "admin", "rola": "admin"}
    return client


def test_set_formula_override(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1/formula-override", json={"produkt": "Cheminox_K", "formula": "sm"})
    assert rv.status_code == 200, rv.get_json()
    j = rv.get_json()
    assert j["ok"] is True
    assert j["produkt"] == "Cheminox_K"
    assert j["formula"] == "sm"

    row = db.execute("SELECT formula FROM parametry_etapy WHERE id=10").fetchone()
    assert row["formula"] == "sm"


def test_clear_formula_override(monkeypatch, db):
    _seed(db)
    db.execute("UPDATE parametry_etapy SET formula='sm' WHERE id=10")
    db.commit()
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1/formula-override", json={"produkt": "Cheminox_K", "formula": None})
    assert rv.status_code == 200

    row = db.execute("SELECT formula FROM parametry_etapy WHERE id=10").fetchone()
    assert row["formula"] is None


def test_clear_formula_override_via_empty_string(monkeypatch, db):
    _seed(db)
    db.execute("UPDATE parametry_etapy SET formula='sm' WHERE id=10")
    db.commit()
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1/formula-override", json={"produkt": "Cheminox_K", "formula": "   "})
    assert rv.status_code == 200

    row = db.execute("SELECT formula FROM parametry_etapy WHERE id=10").fetchone()
    assert row["formula"] is None


def test_404_when_no_binding(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1/formula-override", json={"produkt": "Other", "formula": "sm"})
    assert rv.status_code == 404


def test_kontekst_param_overrides_default(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1/formula-override", json={
        "produkt": "Other", "formula": "sm * 2", "kontekst": "sulfonowanie"
    })
    assert rv.status_code == 200

    row = db.execute("SELECT formula FROM parametry_etapy WHERE id=11").fetchone()
    assert row["formula"] == "sm * 2"


def test_audit_event_emitted(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1/formula-override", json={"produkt": "Cheminox_K", "formula": "sm"})
    assert rv.status_code == 200

    rows = db.execute(
        "SELECT entity_id, entity_label, payload_json FROM audit_log WHERE event_type='parametr.updated'"
    ).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["entity_id"] == 1
    assert r["entity_label"] == "sa"
    payload = json.loads(r["payload_json"])
    assert payload["action"] == "formula_override_set"
    assert payload["produkt"] == "Cheminox_K"
    assert payload["kontekst"] == "analiza_koncowa"
    assert payload["formula_old"] is None
    assert payload["formula_new"] == "sm"
    assert payload["kod"] == "sa"


def test_audit_clear_action(monkeypatch, db):
    _seed(db)
    db.execute("UPDATE parametry_etapy SET formula='sm' WHERE id=10")
    db.commit()
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1/formula-override", json={"produkt": "Cheminox_K", "formula": None})
    assert rv.status_code == 200

    payload = json.loads(db.execute(
        "SELECT payload_json FROM audit_log WHERE event_type='parametr.updated'"
    ).fetchone()["payload_json"])
    assert payload["action"] == "formula_override_cleared"
    assert payload["formula_old"] == "sm"
    assert payload["formula_new"] is None


def test_admin_only(monkeypatch, db):
    _seed(db)
    import mbr.db, mbr.parametry.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.parametry.routes, "db_session", fake_db_session)

    from mbr.app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "lab1", "rola": "laborant"}

    rv = client.put("/api/parametry/1/formula-override", json={"produkt": "Cheminox_K", "formula": "sm"})
    assert rv.status_code == 403
