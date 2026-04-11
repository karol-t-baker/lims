"""Tests for mbr/shared/audit.py"""

import json
import sqlite3
import pytest

from mbr.shared import audit


def test_event_type_constants_follow_naming_convention():
    """All event_type constants are lowercase dot-separated strings."""
    names = [
        audit.EVENT_AUTH_LOGIN,
        audit.EVENT_AUTH_LOGOUT,
        audit.EVENT_WORKER_CREATED,
        audit.EVENT_EBR_WYNIK_SAVED,
        audit.EVENT_CERT_GENERATED,
        audit.EVENT_MBR_TEMPLATE_UPDATED,
        audit.EVENT_SYSTEM_MIGRATION_APPLIED,
    ]
    for name in names:
        assert name == name.lower()
        assert "." in name
        assert " " not in name


def test_shift_required_error_is_exception():
    """ShiftRequiredError is an Exception subclass with a default message."""
    err = audit.ShiftRequiredError()
    assert isinstance(err, Exception)
    assert "shift" in str(err).lower() or "zmiana" in str(err).lower()


# ---------- diff_fields ----------

def test_diff_fields_returns_empty_when_no_changes():
    old = {"a": 1, "b": 2, "c": 3}
    new = {"a": 1, "b": 2, "c": 3}
    assert audit.diff_fields(old, new, ["a", "b", "c"]) == []


def test_diff_fields_only_reports_keys_in_keys_list():
    old = {"a": 1, "b": 2, "ignored": "old"}
    new = {"a": 1, "b": 99, "ignored": "new"}
    result = audit.diff_fields(old, new, ["a", "b"])
    assert result == [{"pole": "b", "stara": 2, "nowa": 99}]


def test_diff_fields_reports_multiple_changes_in_order_of_keys():
    old = {"a": 1, "b": 2, "c": 3}
    new = {"a": 10, "b": 2, "c": 30}
    result = audit.diff_fields(old, new, ["a", "b", "c"])
    assert result == [
        {"pole": "a", "stara": 1, "nowa": 10},
        {"pole": "c", "stara": 3, "nowa": 30},
    ]


def test_diff_fields_serializes_non_scalars_to_json():
    old = {"etapy_json": [{"s": 1}]}
    new = {"etapy_json": [{"s": 1}, {"s": 2}]}
    result = audit.diff_fields(old, new, ["etapy_json"])
    assert len(result) == 1
    assert result[0]["pole"] == "etapy_json"
    # Non-scalars are kept as-is in the returned dict (caller/log_event serializes to JSON).
    assert result[0]["stara"] == [{"s": 1}]
    assert result[0]["nowa"] == [{"s": 1}, {"s": 2}]


def test_diff_fields_handles_none_values():
    old = {"note": None}
    new = {"note": "hello"}
    assert audit.diff_fields(old, new, ["note"]) == [
        {"pole": "note", "stara": None, "nowa": "hello"}
    ]


def test_diff_fields_missing_keys_treated_as_none():
    old = {}
    new = {"a": 1}
    assert audit.diff_fields(old, new, ["a"]) == [
        {"pole": "a", "stara": None, "nowa": 1}
    ]


# ---------- actors_system / actors_explicit ----------

def test_actors_system_returns_single_system_actor():
    result = audit.actors_system()
    assert result == [
        {"worker_id": None, "actor_login": "system", "actor_rola": "system"}
    ]


@pytest.fixture
def workers_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            imie TEXT, nazwisko TEXT, nickname TEXT, inicjaly TEXT,
            login TEXT, rola TEXT
        )
    """)
    db.executemany(
        "INSERT INTO workers (id, imie, nazwisko, nickname, inicjaly, login, rola) VALUES (?,?,?,?,?,?,?)",
        [
            (1, "Anna",  "Kowalska", "AK", "AK", "anna",  "laborant_coa"),
            (2, "Maria", "Wójcik",   "MW", "MW", "maria", "laborant"),
            (3, "Jan",   "Nowak",    "JN", "JN", "jan",   "technolog"),
        ],
    )
    db.commit()
    yield db
    db.close()


def test_actors_explicit_resolves_worker_rows_from_db(workers_db):
    result = audit.actors_explicit(workers_db, [1, 3])
    assert result == [
        {"worker_id": 1, "actor_login": "anna", "actor_rola": "laborant_coa"},
        {"worker_id": 3, "actor_login": "jan",  "actor_rola": "technolog"},
    ]


def test_actors_explicit_raises_on_unknown_worker_id(workers_db):
    with pytest.raises(ValueError, match="unknown worker"):
        audit.actors_explicit(workers_db, [999])


def test_actors_explicit_empty_list_returns_empty():
    db = sqlite3.connect(":memory:")
    assert audit.actors_explicit(db, []) == []
    db.close()


# ---------- actors_from_request ----------

from flask import Flask


@pytest.fixture
def app_with_workers(workers_db):
    """Flask app with a test request context — workers DB available via g."""
    app = Flask(__name__)
    app.secret_key = "test"
    return app


def test_actors_from_request_admin_returns_single_session_user(app_with_workers, workers_db):
    with app_with_workers.test_request_context():
        from flask import session
        session["user"] = {"login": "jan", "rola": "technolog", "worker_id": 3}
        result = audit.actors_from_request(workers_db)
    assert result == [{"worker_id": 3, "actor_login": "jan", "actor_rola": "technolog"}]


def test_actors_from_request_technolog_ignores_shift(app_with_workers, workers_db):
    with app_with_workers.test_request_context():
        from flask import session
        session["user"] = {"login": "jan", "rola": "technolog", "worker_id": 3}
        session["shift_workers"] = [1, 2]  # should be ignored for technolog
        result = audit.actors_from_request(workers_db)
    assert len(result) == 1
    assert result[0]["worker_id"] == 3


def test_actors_from_request_laborant_returns_all_shift_workers(app_with_workers, workers_db):
    with app_with_workers.test_request_context():
        from flask import session
        session["user"] = {"login": "anna", "rola": "laborant", "worker_id": 1}
        session["shift_workers"] = [1, 2]
        result = audit.actors_from_request(workers_db)
    assert len(result) == 2
    assert {a["worker_id"] for a in result} == {1, 2}


def test_actors_from_request_laborant_with_empty_shift_raises(app_with_workers, workers_db):
    with app_with_workers.test_request_context():
        from flask import session
        session["user"] = {"login": "anna", "rola": "laborant", "worker_id": 1}
        session["shift_workers"] = []
        with pytest.raises(audit.ShiftRequiredError):
            audit.actors_from_request(workers_db)


def test_actors_from_request_laborant_with_missing_shift_key_raises(app_with_workers, workers_db):
    with app_with_workers.test_request_context():
        from flask import session
        session["user"] = {"login": "anna", "rola": "laborant", "worker_id": 1}
        # No shift_workers in session at all
        with pytest.raises(audit.ShiftRequiredError):
            audit.actors_from_request(workers_db)


def test_actors_from_request_laborant_kj_ignores_shift_returns_single(app_with_workers, workers_db):
    with app_with_workers.test_request_context():
        from flask import session
        session["user"] = {"login": "anna", "rola": "laborant_kj", "worker_id": 1}
        session["shift_workers"] = [1, 2, 3]
        result = audit.actors_from_request(workers_db)
    assert len(result) == 1
    assert result[0]["worker_id"] == 1
    assert result[0]["actor_rola"] == "laborant_kj"


# ---------- log_event ----------

@pytest.fixture
def audit_db(workers_db):
    """Extend workers_db with audit_log + audit_log_actors tables."""
    workers_db.executescript("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            dt              TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            entity_type     TEXT,
            entity_id       INTEGER,
            entity_label    TEXT,
            diff_json       TEXT,
            payload_json    TEXT,
            context_json    TEXT,
            request_id      TEXT,
            ip              TEXT,
            user_agent      TEXT,
            result          TEXT NOT NULL DEFAULT 'ok'
        );
        CREATE TABLE IF NOT EXISTS audit_log_actors (
            audit_id        INTEGER NOT NULL REFERENCES audit_log(id) ON DELETE CASCADE,
            worker_id       INTEGER,
            actor_login     TEXT NOT NULL,
            actor_rola      TEXT NOT NULL,
            PRIMARY KEY (audit_id, actor_login)
        );
    """)
    workers_db.commit()
    return workers_db


def test_log_event_writes_row_with_system_actor(audit_db):
    audit_id = audit.log_event(
        audit.EVENT_SYSTEM_MIGRATION_APPLIED,
        entity_type=None,
        entity_id=None,
        payload={"migration": "audit_log_v2"},
        actors=audit.actors_system(),
        db=audit_db,
    )
    assert isinstance(audit_id, int)
    assert audit_id > 0

    row = audit_db.execute("SELECT * FROM audit_log WHERE id=?", (audit_id,)).fetchone()
    assert row["event_type"] == "system.migration.applied"
    assert row["entity_type"] is None
    assert row["result"] == "ok"
    assert row["dt"] is not None
    assert json.loads(row["payload_json"])["migration"] == "audit_log_v2"

    actors = audit_db.execute(
        "SELECT worker_id, actor_login, actor_rola FROM audit_log_actors WHERE audit_id=?",
        (audit_id,)
    ).fetchall()
    assert len(actors) == 1
    assert actors[0]["worker_id"] is None
    assert actors[0]["actor_login"] == "system"


def test_log_event_writes_multiple_actors(audit_db):
    audit_id = audit.log_event(
        audit.EVENT_EBR_WYNIK_SAVED,
        entity_type="ebr",
        entity_id=42,
        entity_label="Szarża 2026/42",
        diff=[{"pole": "temperatura", "stara": 85, "nowa": 87}],
        actors=[
            {"worker_id": 1, "actor_login": "anna", "actor_rola": "laborant"},
            {"worker_id": 2, "actor_login": "maria", "actor_rola": "laborant"},
        ],
        db=audit_db,
    )
    actors = audit_db.execute(
        "SELECT worker_id FROM audit_log_actors WHERE audit_id=? ORDER BY worker_id",
        (audit_id,),
    ).fetchall()
    assert [a["worker_id"] for a in actors] == [1, 2]


def test_log_event_serializes_diff_and_payload_as_json(audit_db):
    audit_id = audit.log_event(
        audit.EVENT_MBR_TEMPLATE_UPDATED,
        entity_type="mbr",
        entity_id=7,
        diff=[{"pole": "etapy_json", "stara": [{"s": 1}], "nowa": [{"s": 2}]}],
        payload={"reason": "recipe fix"},
        actors=audit.actors_system(),
        db=audit_db,
    )
    row = audit_db.execute(
        "SELECT diff_json, payload_json FROM audit_log WHERE id=?", (audit_id,)
    ).fetchone()
    diff = json.loads(row["diff_json"])
    assert diff[0]["nowa"] == [{"s": 2}]
    payload = json.loads(row["payload_json"])
    assert payload["reason"] == "recipe fix"


def test_log_event_accepts_result_error(audit_db):
    """auth.login with result='error' for failed login attempts."""
    audit_id = audit.log_event(
        audit.EVENT_AUTH_LOGIN,
        payload={"attempted_login": "ghost"},
        result="error",
        actors=[{"worker_id": None, "actor_login": "ghost", "actor_rola": "unknown"}],
        db=audit_db,
    )
    row = audit_db.execute("SELECT result FROM audit_log WHERE id=?", (audit_id,)).fetchone()
    assert row["result"] == "error"


def test_log_event_resolves_actors_from_request_when_not_provided(audit_db):
    """If `actors=` not passed, helper resolves from Flask session."""
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        from flask import session, g
        session["user"] = {"login": "jan", "rola": "technolog", "worker_id": 3}
        g.audit_request_id = "req-abc-123"

        audit_id = audit.log_event(
            audit.EVENT_MBR_TEMPLATE_CREATED,
            entity_type="mbr",
            entity_id=1,
            db=audit_db,
        )

    row = audit_db.execute(
        "SELECT request_id FROM audit_log WHERE id=?", (audit_id,)
    ).fetchone()
    assert row["request_id"] == "req-abc-123"

    actors = audit_db.execute(
        "SELECT worker_id, actor_login FROM audit_log_actors WHERE audit_id=?",
        (audit_id,),
    ).fetchall()
    assert len(actors) == 1
    assert actors[0]["worker_id"] == 3


def test_log_event_writes_in_caller_transaction_rollback_removes_both(audit_db):
    """If caller rolls back, audit row AND actor row must also roll back."""
    audit_db.execute("BEGIN")
    audit_id = audit.log_event(
        audit.EVENT_WORKER_CREATED,
        entity_type="worker",
        entity_id=999,
        actors=audit.actors_system(),
        db=audit_db,
    )
    # Simulate business-logic failure → rollback
    audit_db.rollback()

    rows = audit_db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE id=?", (audit_id,)
    ).fetchone()[0]
    actors = audit_db.execute(
        "SELECT COUNT(*) FROM audit_log_actors WHERE audit_id=?", (audit_id,)
    ).fetchone()[0]
    assert rows == 0
    assert actors == 0


# ---------- Flask wiring ----------

def test_before_request_sets_unique_audit_request_id(monkeypatch, tmp_path):
    """Each Flask request gets its own UUID in g.audit_request_id."""
    # Point DB to a temp file so create_app() can init tables without clobbering real data
    import mbr.db as mbr_db
    monkeypatch.setattr(mbr_db, "DB_PATH", tmp_path / "test.sqlite")

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    captured = []
    @app.route("/__probe__")
    def _probe():
        from flask import g
        captured.append(g.audit_request_id)
        return "ok"

    client = app.test_client()
    client.get("/__probe__")
    client.get("/__probe__")

    assert len(captured) == 2
    assert captured[0] is not None
    assert captured[1] is not None
    assert captured[0] != captured[1]  # unique per request


def test_shift_required_error_returns_http_400_json(monkeypatch, tmp_path):
    """ShiftRequiredError raised in a route → HTTP 400 with {"error": "shift_required"}."""
    import mbr.db as mbr_db
    monkeypatch.setattr(mbr_db, "DB_PATH", tmp_path / "test.sqlite")

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    @app.route("/__probe_shift__")
    def _probe_shift():
        raise audit.ShiftRequiredError()

    client = app.test_client()
    resp = client.get("/__probe_shift__")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body == {"error": "shift_required"}
