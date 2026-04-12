"""Tests for Phase 4 wyniki (lab results) audit events."""

import json as _json
import sqlite3
import pytest
from contextlib import contextmanager
from datetime import datetime

from mbr.models import init_mbr_tables


_PARAMETRY_LAB = _json.dumps({
    "analiza": {
        "pola": [
            {"kod": "sm", "tag": "SM", "min": 30, "max": 50},
            {"kod": "ph", "tag": "pH", "min": 6, "max": 9},
        ]
    }
})


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
    # Seed an active MBR template with parametry_lab
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia) VALUES (?, 1, 'active', '[]', ?, 'test', ?)",
        ("Chegina_K7", _PARAMETRY_LAB, now),
    )
    conn.commit()
    yield conn
    conn.close()


def _make_client(monkeypatch, db, rola="lab", shift_workers=None):
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
    return _make_client(monkeypatch, db, rola="lab", shift_workers=[1])


def _create_batch(client, db):
    """Helper: create an EBR and return its id."""
    client.post("/laborant/szarze/new", data={
        "produkt": "Chegina_K7", "nr_partii": "W/2026",
        "nr_amidatora": "", "nr_mieszalnika": "", "wielkosc_kg": "0",
    })
    return db.execute("SELECT ebr_id FROM ebr_batches LIMIT 1").fetchone()["ebr_id"]


# ---------- POST /laborant/ebr/<id>/save ----------

def test_save_wyniki_logs_single_entry_per_submit(client, db):
    """POSTing 2 params in one /save produces ONE audit entry with 2-element diff."""
    ebr_id = _create_batch(client, db)

    resp = client.post(f"/laborant/ebr/{ebr_id}/save", json={
        "sekcja": "analiza",
        "values": {
            "sm": {"wartosc": "40.5", "komentarz": ""},
            "ph": {"wartosc": "7.2", "komentarz": ""},
        },
    })
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT event_type, diff_json, payload_json FROM audit_log "
        "WHERE event_type IN ('ebr.wynik.saved', 'ebr.wynik.updated')"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "ebr.wynik.saved"

    diff = _json.loads(rows[0]["diff_json"])
    assert len(diff) == 2
    kods = {d["pole"] for d in diff}
    assert kods == {"sm", "ph"}
    # First save: old values are None
    for d in diff:
        assert d["stara"] is None

    payload = _json.loads(rows[0]["payload_json"])
    assert payload["sekcja"] == "analiza"


def test_save_wyniki_resave_uses_updated_event(client, db):
    """First save -> ebr.wynik.saved; second save with changed value -> ebr.wynik.updated with diff."""
    ebr_id = _create_batch(client, db)

    # First save
    client.post(f"/laborant/ebr/{ebr_id}/save", json={
        "sekcja": "analiza",
        "values": {
            "sm": {"wartosc": "40.5", "komentarz": ""},
            "ph": {"wartosc": "7.2", "komentarz": ""},
        },
    })

    # Second save — change sm, keep ph
    resp = client.post(f"/laborant/ebr/{ebr_id}/save", json={
        "sekcja": "analiza",
        "values": {
            "sm": {"wartosc": "42.0", "komentarz": ""},
            "ph": {"wartosc": "7.2", "komentarz": ""},
        },
    })
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT event_type, diff_json FROM audit_log "
        "WHERE event_type IN ('ebr.wynik.saved', 'ebr.wynik.updated') "
        "ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["event_type"] == "ebr.wynik.saved"
    assert rows[1]["event_type"] == "ebr.wynik.updated"

    # Second entry's diff should show sm changed, ph unchanged (not in diff)
    diff = _json.loads(rows[1]["diff_json"])
    assert len(diff) == 1
    assert diff[0]["pole"] == "sm"
    assert diff[0]["stara"] == 40.5
    assert diff[0]["nowa"] == 42.0


# ---------- POST /api/ebr/<id>/samples ----------

def test_save_samples_logs_event(client, db):
    """Saving titration samples logs ebr.wynik.updated with type=samples."""
    ebr_id = _create_batch(client, db)

    # First save a wynik so the row exists
    client.post(f"/laborant/ebr/{ebr_id}/save", json={
        "sekcja": "analiza",
        "values": {"sm": {"wartosc": "40.5", "komentarz": ""}},
    })

    # Now save samples for that parameter
    resp = client.post(f"/api/ebr/{ebr_id}/samples", json={
        "sekcja": "analiza",
        "kod_parametru": "sm",
        "tag": "SM",
        "samples": [{"nawazka": 1.0, "objetosc": 2.5}],
    })
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT event_type, payload_json FROM audit_log "
        "WHERE event_type = 'ebr.wynik.updated' "
        "ORDER BY id"
    ).fetchall()
    # Should have at least one samples entry (last one)
    samples_entries = [r for r in rows if '"type": "samples"' in (r["payload_json"] or "")]
    assert len(samples_entries) == 1
    payload = _json.loads(samples_entries[0]["payload_json"])
    assert payload["sekcja"] == "analiza"
    assert payload["kod"] == "sm"
    assert payload["type"] == "samples"
