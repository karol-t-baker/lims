"""Tests for Phase 3 auth instrumentation: login/logout/password_changed."""

import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables
from mbr.auth.models import create_user


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _make_client(monkeypatch, db, rola="admin"):
    """Build a Flask test client with the in-memory db patched in."""
    import mbr.db
    import mbr.auth.routes
    import mbr.admin.routes
    import mbr.admin.audit_routes
    import mbr.laborant.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.auth.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.audit_routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    client = app.test_client()
    if rola is not None:
        with client.session_transaction() as sess:
            sess["user"] = {"login": "tester", "rola": rola, "imie_nazwisko": None}
    return client


@pytest.fixture
def admin_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="admin")


@pytest.fixture
def laborant_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="laborant")


@pytest.fixture
def anon_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola=None)


# ---------- POST /api/users/<id>/password ----------

def test_change_password_logs_event(admin_client, db):
    """Admin changes another user's password → audit_log entry exists with
    target_user_id + target_user_login in payload (NOT the password)."""
    target_id = create_user(db, login="kowalski", password="oldpass1", rola="laborant")

    resp = admin_client.post(
        f"/api/users/{target_id}/password",
        json={"new_password": "newpass2"},
    )
    assert resp.status_code == 200

    # Verify password actually changed
    from mbr.auth.models import verify_user
    assert verify_user(db, "kowalski", "newpass2") is not None
    assert verify_user(db, "kowalski", "oldpass1") is None

    # Audit entry exists
    rows = db.execute(
        "SELECT event_type, entity_type, entity_id, entity_label, payload_json "
        "FROM audit_log WHERE event_type='auth.password_changed'"
    ).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["entity_type"] == "user"
    assert r["entity_id"] == target_id
    assert r["entity_label"] == "kowalski"

    import json as _json
    payload = _json.loads(r["payload_json"])
    assert payload["target_user_id"] == target_id
    assert payload["target_user_login"] == "kowalski"
    # CRITICAL: no password material anywhere in the payload
    assert "password" not in str(payload).lower()
    assert "newpass" not in str(payload).lower()
    assert "newpass2" not in r["payload_json"]
    assert "oldpass1" not in r["payload_json"]


def test_change_password_forbidden_for_non_admin(laborant_client, db):
    target_id = create_user(db, login="kowalski", password="oldpass1", rola="laborant")
    resp = laborant_client.post(
        f"/api/users/{target_id}/password", json={"new_password": "newpass2"}
    )
    assert resp.status_code == 403
    # Password unchanged
    from mbr.auth.models import verify_user
    assert verify_user(db, "kowalski", "oldpass1") is not None
    # No audit entry
    count = db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE event_type='auth.password_changed'"
    ).fetchone()[0]
    assert count == 0


# ---------- POST /login ----------

def test_login_success_logs_auth_login_ok(anon_client, db):
    """Successful login → audit entry with result='ok' and session user as actor."""
    create_user(db, login="anna", password="goodpass", rola="laborant")

    resp = anon_client.post("/login", data={"login": "anna", "password": "goodpass"})
    assert resp.status_code in (302, 303)  # redirect after successful login

    rows = db.execute(
        "SELECT id, event_type, result, payload_json FROM audit_log WHERE event_type='auth.login'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result"] == "ok"

    actors = db.execute(
        "SELECT actor_login, actor_rola FROM audit_log_actors WHERE audit_id=?",
        (rows[0]["id"],),
    ).fetchall()
    assert len(actors) == 1
    assert actors[0]["actor_login"] == "anna"
    assert actors[0]["actor_rola"] == "laborant"


def test_login_failure_logs_auth_login_error(anon_client, db):
    """Failed login → audit entry with result='error', actor_login='attempted',
    actor_rola='unknown', payload contains attempted_login."""
    create_user(db, login="anna", password="goodpass", rola="laborant")

    resp = anon_client.post("/login", data={"login": "anna", "password": "wrongpass"})
    # Login page re-renders on failure, no redirect
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT id, event_type, result, payload_json FROM audit_log WHERE event_type='auth.login'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result"] == "error"

    import json as _json
    payload = _json.loads(rows[0]["payload_json"])
    assert payload["attempted_login"] == "anna"

    actors = db.execute(
        "SELECT worker_id, actor_login, actor_rola FROM audit_log_actors WHERE audit_id=?",
        (rows[0]["id"],),
    ).fetchall()
    assert len(actors) == 1
    assert actors[0]["worker_id"] is None
    assert actors[0]["actor_login"] == "anna"
    assert actors[0]["actor_rola"] == "unknown"


def test_login_failure_with_unknown_user_still_logs(anon_client, db):
    """Login attempt with completely unknown login → still produces an audit
    entry (result=error). Doesn't crash."""
    resp = anon_client.post(
        "/login", data={"login": "ghost_user", "password": "anything"}
    )
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT id, payload_json FROM audit_log WHERE event_type='auth.login'"
    ).fetchall()
    assert len(rows) == 1

    import json as _json
    payload = _json.loads(rows[0]["payload_json"])
    assert payload["attempted_login"] == "ghost_user"
