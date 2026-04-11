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


# ---------- POST /api/worker/<id>/profile ----------

def test_worker_updated_profile_logs_event(admin_client, db):
    """Profile update produces worker.updated with diff of changed fields only."""
    resp = admin_client.post(
        "/api/worker/1/profile",
        json={"nickname": "AKowalska", "avatar_icon": 5, "avatar_color": 3},
    )
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT id, event_type, entity_type, entity_id, entity_label, diff_json "
        "FROM audit_log WHERE event_type='worker.updated'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["entity_type"] == "worker"
    assert rows[0]["entity_id"] == 1
    assert rows[0]["entity_label"] == "Anna Kowalska"

    import json as _json
    diff = _json.loads(rows[0]["diff_json"])
    fields = {d["pole"]: d for d in diff}
    assert fields["nickname"]["stara"] == "AK"
    assert fields["nickname"]["nowa"] == "AKowalska"
    assert fields["avatar_icon"]["stara"] == 0
    assert fields["avatar_icon"]["nowa"] == 5
    assert fields["avatar_color"]["stara"] == 0
    assert fields["avatar_color"]["nowa"] == 3


def test_worker_profile_no_change_no_log(admin_client, db):
    """If POST sends the same values that already exist, no audit entry."""
    # First call sets nickname to AKowalska
    admin_client.post("/api/worker/1/profile", json={"nickname": "AKowalska"})
    # Second call sends the same value
    admin_client.post("/api/worker/1/profile", json={"nickname": "AKowalska"})

    count = db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE event_type='worker.updated'"
    ).fetchone()[0]
    # Only the first call produced an entry
    assert count == 1


# ---------- POST /api/workers (add) ----------

def test_worker_created_logs_event(admin_client, db):
    resp = admin_client.post(
        "/api/workers",
        json={"imie": "Jan", "nazwisko": "Nowak", "nickname": "Janek"},
    )
    assert resp.status_code == 200
    new_id = resp.get_json()["id"]

    rows = db.execute(
        "SELECT id, entity_type, entity_id, entity_label, payload_json FROM audit_log "
        "WHERE event_type='worker.created'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["entity_type"] == "worker"
    assert rows[0]["entity_id"] == new_id
    assert rows[0]["entity_label"] == "Jan Nowak"

    import json as _json
    payload = _json.loads(rows[0]["payload_json"])
    assert payload["imie"] == "Jan"
    assert payload["nazwisko"] == "Nowak"
    assert payload["inicjaly"] == "JN"
    assert payload["nickname"] == "Janek"


# ---------- POST /api/workers/<id>/toggle ----------

def test_worker_toggled_logs_event(admin_client, db):
    resp = admin_client.post("/api/workers/1/toggle")
    assert resp.status_code == 200
    new_val = resp.get_json()["aktywny"]
    assert new_val == 0  # was 1, now 0

    rows = db.execute(
        "SELECT id, entity_type, entity_id, entity_label, diff_json FROM audit_log "
        "WHERE event_type='worker.updated' AND entity_id=1"
    ).fetchall()
    assert len(rows) == 1

    import json as _json
    diff = _json.loads(rows[0]["diff_json"])
    assert diff == [{"pole": "aktywny", "stara": 1, "nowa": 0}]


def test_worker_toggled_unknown_returns_404_no_log(admin_client, db):
    resp = admin_client.post("/api/workers/999/toggle")
    assert resp.status_code == 404
    count = db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE event_type='worker.updated'"
    ).fetchone()[0]
    assert count == 0
