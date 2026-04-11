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
