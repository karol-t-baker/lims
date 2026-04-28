"""PUT /api/parametry/<id> audit covers precision + aktywny in addition to label/name_en/method_code."""
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
        "INSERT INTO parametry_analityczne (id, kod, label, typ, name_en, method_code, precision, aktywny) "
        "VALUES (1, 'nd20', 'Wsp. zalamania', 'bezposredni', 'Refractive index', 'PN-EN ISO 5661', 4, 1)"
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


def test_put_parametry_audit_precision_change(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1", json={"precision": 2})
    assert rv.status_code == 200

    rows = db.execute(
        "SELECT diff_json FROM audit_log WHERE event_type='parametr.updated'"
    ).fetchall()
    assert len(rows) == 1
    diff = json.loads(rows[0]["diff_json"])
    assert diff == [{"pole": "precision", "stara": 4, "nowa": 2}]


def test_put_parametry_audit_aktywny_toggle(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1", json={"aktywny": 0})
    assert rv.status_code == 200

    rows = db.execute(
        "SELECT diff_json FROM audit_log WHERE event_type='parametr.updated'"
    ).fetchall()
    assert len(rows) == 1
    diff = json.loads(rows[0]["diff_json"])
    assert diff == [{"pole": "aktywny", "stara": 1, "nowa": 0}]


def test_put_parametry_audit_combined_label_precision(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1", json={"label": "Wsp. zalamania nD20", "precision": 5})
    assert rv.status_code == 200

    rows = db.execute(
        "SELECT diff_json FROM audit_log WHERE event_type='parametr.updated'"
    ).fetchall()
    assert len(rows) == 1
    diff = json.loads(rows[0]["diff_json"])
    fields = sorted(d["pole"] for d in diff)
    assert fields == ["label", "precision"]
