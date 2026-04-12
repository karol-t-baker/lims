"""Tests for Phase 4 uwagi consolidation — audit_log as SSOT."""

import json as _json
import sqlite3
import pytest
from contextlib import contextmanager
from datetime import datetime

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (999, 'Test', 'User', 'TU', 'testuser', 1)"
    )
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia) VALUES (?, 1, 'active', '[]', '{}', 'test', ?)",
        ("TestP", now),
    )
    mbr_id = conn.execute("SELECT mbr_id FROM mbr_templates").fetchone()["mbr_id"]
    conn.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, typ) "
        "VALUES (?, 'TestP__1', '1/2026', ?, 'open', 'szarza')",
        (mbr_id, now),
    )
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def ebr_id(db):
    return db.execute("SELECT ebr_id FROM ebr_batches LIMIT 1").fetchone()["ebr_id"]


def _make_client(monkeypatch, db):
    import mbr.db
    import mbr.laborant.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "testuser", "rola": "lab"}
        sess["shift_workers"] = [999]
    return client


@pytest.fixture
def client(monkeypatch, db, ebr_id):
    return _make_client(monkeypatch, db)


def test_save_uwagi_writes_to_audit_not_history(client, db, ebr_id):
    """PUT /api/ebr/<id>/uwagi writes to audit_log, NOT ebr_uwagi_history."""
    resp = client.put(f"/api/ebr/{ebr_id}/uwagi", json={"tekst": "Nowa notatka"})
    assert resp.status_code == 200

    # audit_log has the entry
    audit_rows = db.execute(
        "SELECT event_type, payload_json FROM audit_log WHERE event_type='ebr.uwagi.updated'"
    ).fetchall()
    assert len(audit_rows) == 1
    payload = _json.loads(audit_rows[0]["payload_json"])
    assert payload["action"] == "create"

    # ebr_uwagi_history should have ZERO new rows (old mechanism disabled)
    history_count = db.execute("SELECT COUNT(*) FROM ebr_uwagi_history").fetchone()[0]
    assert history_count == 0


def test_get_uwagi_reads_from_audit_log(client, db, ebr_id):
    """GET /api/ebr/<id>/uwagi returns history from audit_log, not ebr_uwagi_history."""
    # Create + update via PUT
    client.put(f"/api/ebr/{ebr_id}/uwagi", json={"tekst": "First"})
    client.put(f"/api/ebr/{ebr_id}/uwagi", json={"tekst": "Second"})

    resp = client.get(f"/api/ebr/{ebr_id}/uwagi")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["tekst"] == "Second"
    assert len(data["historia"]) >= 1  # at least the create event
    # Each historia item has the expected shape
    for h in data["historia"]:
        assert "tekst" in h or "action" in h
        assert "autor" in h
        assert "dt" in h


def test_get_uwagi_returns_compatible_dict_shape(client, db, ebr_id):
    """The dict shape from get_uwagi must match the old format:
    {tekst, dt, autor, historia: [{tekst, action, autor, dt}]}"""
    client.put(f"/api/ebr/{ebr_id}/uwagi", json={"tekst": "Test"})

    resp = client.get(f"/api/ebr/{ebr_id}/uwagi")
    data = resp.get_json()

    # Top level
    assert "tekst" in data
    assert "dt" in data
    assert "autor" in data
    assert "historia" in data
    assert isinstance(data["historia"], list)

    # Historia items
    if data["historia"]:
        h = data["historia"][0]
        assert "tekst" in h
        assert "action" in h
        assert "autor" in h
        assert "dt" in h
