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
            imie TEXT NOT NULL, nazwisko TEXT NOT NULL, inicjaly TEXT NOT NULL,
            nickname TEXT DEFAULT '', avatar_icon INTEGER DEFAULT 0,
            avatar_color INTEGER DEFAULT 0, aktywny INTEGER NOT NULL DEFAULT 1
        )
    """)
    db.executemany(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname) VALUES (?,?,?,?,?)",
        [
            (1, "Anna",  "Kowalska", "AK", "AK"),
            (2, "Maria", "Wójcik",   "MW", "MW"),
            (3, "Jan",   "Nowak",    "JN", "JN"),
        ],
    )
    db.commit()
    yield db
    db.close()


def test_actors_explicit_resolves_worker_rows_from_db(workers_db):
    result = audit.actors_explicit(workers_db, [1, 3])
    assert result == [
        {"worker_id": 1, "actor_login": "AK", "actor_rola": "laborant"},
        {"worker_id": 3, "actor_login": "JN", "actor_rola": "laborant"},
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


# ---------- Smoke test: full write path through a real Flask route ----------

def test_smoke_log_event_through_flask_route(monkeypatch, tmp_path):
    """Real Flask route calls log_event(); verify row landed with correct
    request_id, actors, and serialized payload."""
    import mbr.db as mbr_db
    db_path = tmp_path / "smoke.sqlite"
    monkeypatch.setattr(mbr_db, "DB_PATH", db_path)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    # Seed one worker so actors_from_request can resolve the session user.
    # Note: current workers DDL lacks login/rola columns — actors_from_request
    # for single-actor roles (technolog) reads those from session anyway.
    with mbr_db.db_session() as db:
        db.execute(
            "INSERT INTO workers (imie, nazwisko, nickname, inicjaly) VALUES (?,?,?,?)",
            ("Test", "User", "TU", "TU"),
        )
        db.commit()
        worker_id = db.execute("SELECT id FROM workers WHERE inicjaly='TU'").fetchone()[0]

    @app.route("/__probe_log__", methods=["POST"])
    def _probe_log():
        from flask import session
        from mbr.db import db_session as _ds
        session["user"] = {"login": "tu", "rola": "technolog", "worker_id": worker_id}
        with _ds() as db:
            aid = audit.log_event(
                audit.EVENT_MBR_TEMPLATE_UPDATED,
                entity_type="mbr",
                entity_id=123,
                entity_label="K40GLO v3",
                diff=[{"pole": "etapy_json", "stara": "old", "nowa": "new"}],
                db=db,
            )
            db.commit()
        return {"id": aid}

    client = app.test_client()
    resp = client.post("/__probe_log__")
    assert resp.status_code == 200
    audit_id = resp.get_json()["id"]

    with mbr_db.db_session() as db:
        row = db.execute(
            "SELECT event_type, entity_type, entity_id, entity_label, request_id FROM audit_log WHERE id=?",
            (audit_id,),
        ).fetchone()
        assert row["event_type"] == "mbr.template.updated"
        assert row["entity_type"] == "mbr"
        assert row["entity_id"] == 123
        assert row["entity_label"] == "K40GLO v3"
        assert row["request_id"] is not None

        actors = db.execute(
            "SELECT worker_id, actor_login, actor_rola FROM audit_log_actors WHERE audit_id=?",
            (audit_id,),
        ).fetchall()
        assert len(actors) == 1
        assert actors[0]["worker_id"] == worker_id
        assert actors[0]["actor_login"] == "tu"
        assert actors[0]["actor_rola"] == "technolog"


# ---------- query_audit_log fixtures ----------

@pytest.fixture
def queryable_audit_db(audit_db):
    """audit_db fixture with several seed events spanning event types and dates."""
    import json as _json
    rows = [
        # (dt,                event_type,           entity_type, entity_id, entity_label,    diff_json,                              payload_json,        request_id)
        ("2026-04-01T08:00:00", "auth.login",         None,        None,      None,            None,                                   '{"login":"alice"}', "req-1"),
        ("2026-04-01T09:15:00", "ebr.wynik.saved",    "ebr",       42,        "Szarża 2026/42", '[{"pole":"sm","stara":85,"nowa":87}]', None,                "req-2"),
        ("2026-04-02T10:30:00", "ebr.wynik.saved",    "ebr",       42,        "Szarża 2026/42", '[{"pole":"ph","stara":7,"nowa":7.2}]', None,                "req-3"),
        ("2026-04-03T11:00:00", "cert.generated",     "cert",      7,         "Świad. K40GLO",  None,                                   '{"path":"/x.pdf"}', "req-4"),
        ("2026-04-05T12:45:00", "auth.login",         None,        None,      None,            None,                                   '{"login":"bob"}',   "req-5"),
        ("2026-04-08T13:00:00", "ebr.wynik.saved",    "ebr",       43,        "Szarża 2026/43", '[{"pole":"sm","stara":80,"nowa":82}]', None,                "req-6"),
    ]
    for r in rows:
        cur = audit_db.execute(
            """INSERT INTO audit_log
               (dt, event_type, entity_type, entity_id, entity_label,
                diff_json, payload_json, request_id, result)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ok')""",
            r,
        )
        # Always at least one actor — alternate between worker 1 and worker 2
        wid = 1 if cur.lastrowid % 2 == 1 else 2
        login = "anna" if wid == 1 else "maria"
        audit_db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, ?, ?, 'laborant')",
            (cur.lastrowid, wid, login),
        )
    audit_db.commit()
    return audit_db


# ---------- query_audit_log ----------

def test_query_returns_empty_when_no_rows(audit_db):
    rows, total = audit.query_audit_log(audit_db)
    assert rows == []
    assert total == 0


def test_query_returns_all_rows_with_actors(queryable_audit_db):
    rows, total = audit.query_audit_log(queryable_audit_db)
    assert total == 6
    assert len(rows) == 6
    # Each row has an actors list (>=1 element)
    for r in rows:
        assert "actors" in r
        assert len(r["actors"]) >= 1
        assert "actor_login" in r["actors"][0]


def test_query_filter_by_dt_range(queryable_audit_db):
    rows, total = audit.query_audit_log(
        queryable_audit_db,
        dt_from="2026-04-02",
        dt_to="2026-04-05",
    )
    assert total == 3  # 2026-04-02, 04-03, 04-05
    assert all(r["dt"][:10] in ("2026-04-02", "2026-04-03", "2026-04-05") for r in rows)


def test_query_filter_by_event_type_glob(queryable_audit_db):
    rows, total = audit.query_audit_log(
        queryable_audit_db, event_type_glob="auth.*"
    )
    assert total == 2
    assert all(r["event_type"].startswith("auth.") for r in rows)


def test_query_filter_by_event_type_exact(queryable_audit_db):
    rows, total = audit.query_audit_log(
        queryable_audit_db, event_type_glob="cert.generated"
    )
    assert total == 1
    assert rows[0]["event_type"] == "cert.generated"


def test_query_filter_by_entity(queryable_audit_db):
    rows, total = audit.query_audit_log(
        queryable_audit_db, entity_type="ebr", entity_id=42
    )
    assert total == 2
    assert all(r["entity_id"] == 42 for r in rows)


def test_query_filter_by_worker_id_uses_actors_table(queryable_audit_db):
    rows, total = audit.query_audit_log(queryable_audit_db, worker_id=1)
    assert total > 0
    # Every returned row has worker 1 as one of its actors
    for r in rows:
        assert any(a["worker_id"] == 1 for a in r["actors"])


def test_query_filter_by_free_text_searches_label_and_payload(queryable_audit_db):
    # 'K40GLO' is in cert entity_label only
    rows, total = audit.query_audit_log(queryable_audit_db, free_text="K40GLO")
    assert total == 1
    assert rows[0]["entity_label"] == "Świad. K40GLO"

    # 'alice' is only in payload_json of one auth.login
    rows, total = audit.query_audit_log(queryable_audit_db, free_text="alice")
    assert total == 1
    assert "alice" in rows[0]["payload_json"]


def test_query_filter_by_free_text_escapes_like_metacharacters(audit_db):
    """User searching for '100%' or 'foo_bar' should NOT trigger LIKE wildcard expansion."""
    # Seed two rows: one with literal '100%' in label, one with '1009' (would match if % were a wildcard)
    audit_db.execute(
        """INSERT INTO audit_log (dt, event_type, entity_type, entity_id, entity_label, result)
           VALUES ('2026-04-01T08:00:00', 'x.y.z', 'ebr', 1, 'sm 100%', 'ok')"""
    )
    audit_db.execute(
        """INSERT INTO audit_log (dt, event_type, entity_type, entity_id, entity_label, result)
           VALUES ('2026-04-01T09:00:00', 'x.y.z', 'ebr', 2, 'sm 1009', 'ok')"""
    )
    audit_db.commit()

    rows, total = audit.query_audit_log(audit_db, free_text="100%")
    # Only 'sm 100%' must match — not 'sm 1009'
    assert total == 1
    assert rows[0]["entity_label"] == "sm 100%"

    # Underscore literal: search '_bar' should not match '1bar'
    audit_db.execute(
        """INSERT INTO audit_log (dt, event_type, entity_type, entity_id, entity_label, result)
           VALUES ('2026-04-02T08:00:00', 'x.y.z', 'ebr', 3, 'foo_bar', 'ok')"""
    )
    audit_db.execute(
        """INSERT INTO audit_log (dt, event_type, entity_type, entity_id, entity_label, result)
           VALUES ('2026-04-02T09:00:00', 'x.y.z', 'ebr', 4, 'foo1bar', 'ok')"""
    )
    audit_db.commit()

    rows, total = audit.query_audit_log(audit_db, free_text="_bar")
    # Only 'foo_bar' matches; 'foo1bar' does NOT (underscore literal, not wildcard)
    assert total == 1
    assert rows[0]["entity_label"] == "foo_bar"


def test_query_filter_by_request_id(queryable_audit_db):
    rows, total = audit.query_audit_log(queryable_audit_db, request_id="req-3")
    assert total == 1
    assert rows[0]["request_id"] == "req-3"


def test_query_pagination(queryable_audit_db):
    # 6 seeded rows, page size 2
    rows_page1, total = audit.query_audit_log(queryable_audit_db, limit=2, offset=0)
    rows_page2, _ = audit.query_audit_log(queryable_audit_db, limit=2, offset=2)
    rows_page3, _ = audit.query_audit_log(queryable_audit_db, limit=2, offset=4)
    assert total == 6
    assert len(rows_page1) == 2
    assert len(rows_page2) == 2
    assert len(rows_page3) == 2
    # Pages are disjoint
    ids1 = {r["id"] for r in rows_page1}
    ids2 = {r["id"] for r in rows_page2}
    ids3 = {r["id"] for r in rows_page3}
    assert ids1.isdisjoint(ids2)
    assert ids2.isdisjoint(ids3)


# ---------- query_audit_history_for_entity ----------

def test_history_for_entity_returns_only_matching(queryable_audit_db):
    rows = audit.query_audit_history_for_entity(queryable_audit_db, "ebr", 42)
    assert len(rows) == 2
    assert all(r["entity_id"] == 42 for r in rows)
    assert all(r["entity_type"] == "ebr" for r in rows)
    # Sorted DESC by dt
    assert rows[0]["dt"] >= rows[1]["dt"]


def test_history_for_entity_includes_actors(queryable_audit_db):
    rows = audit.query_audit_history_for_entity(queryable_audit_db, "cert", 7)
    assert len(rows) == 1
    assert "actors" in rows[0]
    assert len(rows[0]["actors"]) >= 1
    assert "actor_login" in rows[0]["actors"][0]


# ---------- archive_old_entries ----------

def test_archive_dumps_old_entries_to_jsonl_gz_and_deletes(queryable_audit_db, tmp_path):
    import gzip as _gzip
    archive_dir = tmp_path / "audit_archive"
    archive_dir.mkdir()
    # Cutoff: anything before 2026-04-04 is "old" (4 of 6 rows)
    summary = audit.archive_old_entries(
        queryable_audit_db, "2026-04-04T00:00:00", archive_dir
    )
    assert summary["archived"] == 4
    # Active DB has only 2 originals + 1 system.audit.archived = 3
    remaining = queryable_audit_db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    assert remaining == 3
    # Archive file exists with 4 lines
    archive_file = archive_dir / "audit_2026.jsonl.gz"
    assert archive_file.exists()
    with _gzip.open(archive_file, "rt") as f:
        lines = f.readlines()
    assert len(lines) == 4
    # Each line is valid JSON with our row shape + actors
    import json as _json
    for line in lines:
        parsed = _json.loads(line)
        assert "id" in parsed
        assert "event_type" in parsed
        assert "actors" in parsed


def test_archive_appends_to_existing_year_file(queryable_audit_db, tmp_path):
    import gzip as _gzip
    archive_dir = tmp_path / "audit_archive"
    archive_dir.mkdir()
    # First archive: cutoff 2026-04-02 → 1 old row
    audit.archive_old_entries(queryable_audit_db, "2026-04-02T00:00:00", archive_dir)
    # Second archive: cutoff 2026-04-04 → 3 newly-old rows
    audit.archive_old_entries(queryable_audit_db, "2026-04-04T00:00:00", archive_dir)
    archive_file = archive_dir / "audit_2026.jsonl.gz"
    with _gzip.open(archive_file, "rt") as f:
        lines = f.readlines()
    # 1 + 3 = 4 lines total in the same file (gzip append concatenation)
    assert len(lines) == 4


def test_archive_returns_summary_dict(queryable_audit_db, tmp_path):
    archive_dir = tmp_path / "audit_archive"
    archive_dir.mkdir()
    summary = audit.archive_old_entries(
        queryable_audit_db, "2026-04-04T00:00:00", archive_dir
    )
    assert summary["archived"] == 4
    assert summary["cutoff"] == "2026-04-04T00:00:00"
    assert "audit_2026.jsonl.gz" in summary["file"]


def test_archive_logs_system_audit_archived_event(queryable_audit_db, tmp_path):
    archive_dir = tmp_path / "audit_archive"
    archive_dir.mkdir()
    audit.archive_old_entries(queryable_audit_db, "2026-04-04T00:00:00", archive_dir)
    # The new system.audit.archived event must exist
    rows = queryable_audit_db.execute(
        "SELECT event_type, payload_json FROM audit_log WHERE event_type='system.audit.archived'"
    ).fetchall()
    assert len(rows) == 1
    import json as _json
    payload = _json.loads(rows[0]["payload_json"])
    assert payload["count"] == 4
    assert payload["cutoff"] == "2026-04-04T00:00:00"
    assert "audit_2026.jsonl.gz" in payload["file"]
    # Actor of the archive event is the 'system' virtual actor
    aid_row = queryable_audit_db.execute(
        "SELECT id FROM audit_log WHERE event_type='system.audit.archived'"
    ).fetchone()
    actors = queryable_audit_db.execute(
        "SELECT actor_login, actor_rola, worker_id FROM audit_log_actors WHERE audit_id=?",
        (aid_row[0],),
    ).fetchall()
    assert len(actors) == 1
    assert actors[0]["actor_login"] == "system"
    assert actors[0]["actor_rola"] == "system"
    assert actors[0]["worker_id"] is None


def test_archive_empty_set_does_not_log_or_create_file(audit_db, tmp_path):
    """When zero rows match the cutoff, no system event is logged and no file is created.
    Prevents scheduled archival jobs from littering audit_log with no-op events."""
    archive_dir = tmp_path / "audit_archive"
    archive_dir.mkdir()
    # No seed rows — audit_log is empty
    summary = audit.archive_old_entries(audit_db, "2026-04-04T00:00:00", archive_dir)
    assert summary["archived"] == 0
    assert summary["file"] is None
    assert summary["cutoff"] == "2026-04-04T00:00:00"
    # No system.audit.archived event was logged
    rows = audit_db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE event_type='system.audit.archived'"
    ).fetchone()
    assert rows[0] == 0
    # No file was created
    assert not (archive_dir / "audit_2026.jsonl.gz").exists()


# ---------- audit_actors Jinja filter ----------

def test_audit_actors_filter_joins_logins():
    from mbr.shared.filters import audit_actors_filter
    row = {"actors": [{"actor_login": "AK"}, {"actor_login": "MW"}]}
    assert audit_actors_filter(row) == "AK, MW"


def test_audit_actors_filter_handles_empty():
    from mbr.shared.filters import audit_actors_filter
    assert audit_actors_filter({"actors": []}) == "—"
    assert audit_actors_filter({}) == "—"
