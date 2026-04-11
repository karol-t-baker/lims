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
