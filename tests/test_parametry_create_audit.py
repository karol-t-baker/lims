"""POST /api/parametry emits parametr.created audit event."""
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


def test_post_parametry_emits_create_audit(monkeypatch, db):
    db.execute("DELETE FROM parametry_analityczne")
    db.commit()
    client = _admin_client(monkeypatch, db)

    rv = client.post("/api/parametry", json={
        "kod": "test_kod",
        "label": "Test parameter",
        "typ": "bezposredni",
    })
    assert rv.status_code == 200, rv.get_json()
    new_id = rv.get_json()["id"]

    rows = db.execute(
        "SELECT entity_type, entity_id, entity_label, payload_json "
        "FROM audit_log WHERE event_type='parametr.created'"
    ).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["entity_type"] == "parametr"
    assert r["entity_id"] == new_id
    assert r["entity_label"] == "test_kod"
    payload = json.loads(r["payload_json"])
    assert payload["kod"] == "test_kod"
    assert payload["label"] == "Test parameter"
    assert payload["typ"] == "bezposredni"
