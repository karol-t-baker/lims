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
