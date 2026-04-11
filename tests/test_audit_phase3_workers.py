"""Tests for Phase 3 workers instrumentation."""

import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    # Seed two workers so we can target them
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (1, 'Anna', 'Kowalska', 'AK', 'AK', 1)"
    )
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (2, 'Maria', 'Wojcik', 'MW', 'MW', 1)"
    )
    conn.commit()
    yield conn
    conn.close()


def _make_client(monkeypatch, db, rola="admin"):
    import mbr.db
    import mbr.workers.routes
    import mbr.admin.audit_routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.workers.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.audit_routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": rola, "imie_nazwisko": None}
    return client


@pytest.fixture
def admin_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="admin")


@pytest.fixture
def laborant_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="laborant")


# ---------- POST /api/shift ----------

def test_shift_changed_logs_event(admin_client, db):
    """POST /api/shift produces shift.changed entry with payload={old, new},
    actor = session user (admin), NOT the new shift workers."""
    resp = admin_client.post("/api/shift", json={"worker_ids": [1, 2]})
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT id, event_type, payload_json FROM audit_log WHERE event_type='shift.changed'"
    ).fetchall()
    assert len(rows) == 1

    import json as _json
    payload = _json.loads(rows[0]["payload_json"])
    assert payload["old"] == []  # empty before
    assert payload["new"] == [1, 2]

    # Actor is the admin who made the change, NOT the new shift workers
    actors = db.execute(
        "SELECT actor_login, actor_rola FROM audit_log_actors WHERE audit_id=?",
        (rows[0]["id"],),
    ).fetchall()
    assert len(actors) == 1
    assert actors[0]["actor_login"] == "tester"
    assert actors[0]["actor_rola"] == "admin"


def test_shift_changed_records_old_value(admin_client, db):
    """A second POST captures the old value from the previous POST."""
    admin_client.post("/api/shift", json={"worker_ids": [1]})
    admin_client.post("/api/shift", json={"worker_ids": [1, 2]})

    rows = db.execute(
        "SELECT payload_json FROM audit_log WHERE event_type='shift.changed' ORDER BY id"
    ).fetchall()
    assert len(rows) == 2

    import json as _json
    p2 = _json.loads(rows[1]["payload_json"])
    assert p2["old"] == [1]
    assert p2["new"] == [1, 2]
