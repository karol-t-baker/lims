"""Tests for Phase 4 etapy audit events — 5 stage endpoints."""

import json as _json
import sqlite3
import pytest
from contextlib import contextmanager
from datetime import datetime

from mbr.models import init_mbr_tables
from mbr.etapy.models import init_etapy_status


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
    # Seed an active MBR template for Chegina_K7
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


def _create_batch_with_stages(client, db):
    """Create an EBR via the route and initialize etapy statuses. Returns ebr_id."""
    client.post("/laborant/szarze/new", data={
        "produkt": "Chegina_K7", "nr_partii": "ET/2026",
        "nr_amidatora": "", "nr_mieszalnika": "", "wielkosc_kg": "0",
    })
    ebr_id = db.execute("SELECT ebr_id FROM ebr_batches LIMIT 1").fetchone()["ebr_id"]
    init_etapy_status(db, ebr_id, "Chegina_K7")
    return ebr_id


# ---------- Route 1: POST /api/ebr/<id>/etapy-analizy ----------

def test_save_etap_analizy_logs_event(client, db):
    """Saving stage analyses logs ebr.stage.event_added with type=analizy."""
    ebr_id = _create_batch_with_stages(client, db)

    resp = client.post(f"/api/ebr/{ebr_id}/etapy-analizy", json={
        "etap": "amidowanie",
        "runda": 1,
        "krok": 1,
        "wyniki": {"ph_10proc": 11.76},
    })
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT event_type, entity_type, entity_id, payload_json "
        "FROM audit_log WHERE event_type = 'ebr.stage.event_added'"
    ).fetchall()
    # Filter for analizy type (create_ebr may also log events)
    analizy_rows = [r for r in rows if '"type": "analizy"' in (r["payload_json"] or "")]
    assert len(analizy_rows) == 1
    r = analizy_rows[0]
    assert r["entity_type"] == "ebr"
    assert r["entity_id"] == ebr_id
    payload = _json.loads(r["payload_json"])
    assert payload["type"] == "analizy"
    assert payload["etap"] == "amidowanie"
    assert payload["runda"] == 1


# ---------- Route 2: POST /api/ebr/<id>/korekty ----------

def test_add_korekta_logs_event(client, db):
    """Adding a correction logs ebr.stage.event_added with type=korekta."""
    ebr_id = _create_batch_with_stages(client, db)

    resp = client.post(f"/api/ebr/{ebr_id}/korekty", json={
        "etap": "amidowanie",
        "substancja": "DMAPA",
        "ilosc_kg": 2.5,
        "po_rundzie": 1,
    })
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT payload_json FROM audit_log WHERE event_type = 'ebr.stage.event_added'"
    ).fetchall()
    korekta_rows = [r for r in rows if '"type": "korekta"' in (r["payload_json"] or "")]
    assert len(korekta_rows) == 1
    payload = _json.loads(korekta_rows[0]["payload_json"])
    assert payload["type"] == "korekta"
    assert payload["substancja"] == "DMAPA"
    assert payload["ilosc_kg"] == 2.5


# ---------- Route 3: PUT /api/ebr/<id>/korekty/<kid> ----------

def test_confirm_korekta_logs_event(client, db):
    """Confirming a correction logs ebr.stage.event_updated with type=korekta_confirm."""
    ebr_id = _create_batch_with_stages(client, db)

    # First add a korekta
    resp = client.post(f"/api/ebr/{ebr_id}/korekty", json={
        "etap": "amidowanie",
        "substancja": "NaOH",
        "ilosc_kg": 1.0,
        "po_rundzie": 1,
    })
    assert resp.status_code == 200
    kid = resp.get_json()["id"]

    # Now confirm it
    resp = client.put(f"/api/ebr/{ebr_id}/korekty/{kid}")
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT payload_json FROM audit_log WHERE event_type = 'ebr.stage.event_updated'"
    ).fetchall()
    assert len(rows) == 1
    payload = _json.loads(rows[0]["payload_json"])
    assert payload["type"] == "korekta_confirm"
    assert payload["korekta_id"] == kid


# ---------- Route 4: POST /api/ebr/<id>/etapy-status/zatwierdz ----------

def test_zatwierdz_etap_logs_event(client, db):
    """Approving a stage logs ebr.stage.event_added with type=zatwierdz."""
    ebr_id = _create_batch_with_stages(client, db)

    # amidowanie starts as in_progress for Chegina_K7 (parallel stage)
    resp = client.post(f"/api/ebr/{ebr_id}/etapy-status/zatwierdz", json={
        "etap": "amidowanie",
    })
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT payload_json FROM audit_log WHERE event_type = 'ebr.stage.event_added'"
    ).fetchall()
    zatw_rows = [r for r in rows if '"type": "zatwierdz"' in (r["payload_json"] or "")]
    assert len(zatw_rows) == 1
    payload = _json.loads(zatw_rows[0]["payload_json"])
    assert payload["type"] == "zatwierdz"
    assert payload["etap"] == "amidowanie"


# ---------- Route 5: POST /api/ebr/<id>/etapy-status/skip ----------

def test_skip_etap_logs_event(client, db):
    """Skipping a stage logs ebr.stage.event_added with type=skip."""
    ebr_id = _create_batch_with_stages(client, db)

    # namca starts as in_progress (parallel stage) for Chegina_K7
    resp = client.post(f"/api/ebr/{ebr_id}/etapy-status/skip", json={
        "etap": "namca",
    })
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT payload_json FROM audit_log WHERE event_type = 'ebr.stage.event_added'"
    ).fetchall()
    skip_rows = [r for r in rows if '"type": "skip"' in (r["payload_json"] or "")]
    assert len(skip_rows) == 1
    payload = _json.loads(skip_rows[0]["payload_json"])
    assert payload["type"] == "skip"
    assert payload["etap"] == "namca"
