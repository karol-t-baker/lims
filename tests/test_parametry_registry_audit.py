"""PUT /api/parametry/<id> emits audit event with diff."""
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
        "INSERT INTO parametry_analityczne (id, kod, label, typ, name_en, method_code) "
        "VALUES (1, 'nd20', 'nD20', 'bezposredni', 'Refractive index', 'PN-EN ISO 5661')"
    )
    db.commit()


def _admin_client(monkeypatch, db):
    import mbr.db
    import mbr.parametry.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.parametry.routes, "db_session", fake_db_session)

    from mbr.app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "admin", "rola": "admin", "imie_nazwisko": "Admin"}
    return client


def test_put_parametry_emits_audit_on_label_change(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1", json={"label": "Współczynnik załamania"})
    assert rv.status_code == 200

    rows = db.execute(
        "SELECT event_type, entity_type, entity_id, entity_label, diff_json "
        "FROM audit_log WHERE event_type='parametr.updated'"
    ).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["entity_type"] == "parametr"
    assert r["entity_id"] == 1
    assert r["entity_label"] == "nd20"
    diff = json.loads(r["diff_json"])
    assert diff == [{"pole": "label", "stara": "nD20", "nowa": "Współczynnik załamania"}]


def test_put_parametry_no_audit_when_nothing_changes(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1", json={"label": "nD20"})  # same value
    assert rv.status_code == 200

    rows = db.execute(
        "SELECT 1 FROM audit_log WHERE event_type='parametr.updated'"
    ).fetchall()
    assert len(rows) == 0


def test_put_parametry_audit_multifield_diff(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1", json={
        "label": "Wsp. załamania",
        "name_en": "Refractive index 20°C",
        "method_code": "PN-EN ISO 5661:2024",
    })
    assert rv.status_code == 200

    rows = db.execute(
        "SELECT diff_json FROM audit_log WHERE event_type='parametr.updated'"
    ).fetchall()
    assert len(rows) == 1
    diff = json.loads(rows[0]["diff_json"])
    fields = sorted(d["pole"] for d in diff)
    assert fields == ["label", "method_code", "name_en"]
