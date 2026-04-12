"""Tests for Phase 4 batch lifecycle audit events."""

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
    # Seed workers for shift
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (1, 'Anna', 'Kowalska', 'AK', 'AK', 1)"
    )
    # Seed an active MBR template so create_ebr can find it
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia) VALUES (?, 1, 'active', '[]', '{}', 'test', ?)",
        ("Chegina_K7", now),
    )
    conn.commit()
    yield conn
    conn.close()


def _make_client(monkeypatch, db, rola="laborant", shift_workers=None):
    import mbr.db
    import mbr.laborant.routes
    import mbr.admin.audit_routes
    import mbr.etapy.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.audit_routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.etapy.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": rola, "imie_nazwisko": None}
        if shift_workers is not None:
            sess["shift_workers"] = shift_workers
    return client


@pytest.fixture
def client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="laborant", shift_workers=[1])


@pytest.fixture
def admin_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="admin")


# ---------- POST /laborant/szarze/new ----------

def test_szarze_new_logs_ebr_batch_created(client, db):
    """Creating a new batch logs ebr.batch.created with entity_label and payload."""
    resp = client.post("/laborant/szarze/new", data={
        "produkt": "Chegina_K7",
        "nr_partii": "99/2026",
        "nr_amidatora": "A1",
        "nr_mieszalnika": "M1",
        "wielkosc_kg": "5000",
    })
    # Route redirects after creation
    assert resp.status_code in (302, 303)

    rows = db.execute(
        "SELECT id, event_type, entity_type, entity_id, entity_label, payload_json "
        "FROM audit_log WHERE event_type = 'ebr.batch.created'"
    ).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["entity_type"] == "ebr"
    assert r["entity_id"] is not None  # the new ebr_id
    assert "Chegina_K7" in (r["entity_label"] or "")
    assert "99/2026" in (r["entity_label"] or "")

    payload = _json.loads(r["payload_json"])
    assert payload["produkt"] == "Chegina_K7"
    assert payload["nr_partii"] == "99/2026"

    # Actor is the laborant
    actors = db.execute(
        "SELECT actor_login FROM audit_log_actors WHERE audit_id=?", (r["id"],)
    ).fetchall()
    assert len(actors) == 1


# ---------- POST /api/ebr/<id>/golden ----------

def test_toggle_golden_logs_batch_updated(client, db):
    """Toggling is_golden produces ebr.batch.updated with diff."""
    # First create a batch
    client.post("/laborant/szarze/new", data={
        "produkt": "Chegina_K7", "nr_partii": "1/2026",
        "nr_amidatora": "", "nr_mieszalnika": "", "wielkosc_kg": "0",
    })
    ebr_id = db.execute("SELECT ebr_id FROM ebr_batches LIMIT 1").fetchone()["ebr_id"]

    resp = client.post(f"/api/ebr/{ebr_id}/golden")
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT diff_json FROM audit_log WHERE event_type = 'ebr.batch.updated'"
    ).fetchall()
    assert len(rows) == 1
    diff = _json.loads(rows[0]["diff_json"])
    assert diff == [{"pole": "is_golden", "stara": 0, "nowa": 1}]
