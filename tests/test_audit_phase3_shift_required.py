"""Tests for Phase 3 enforcement: laborant write paths must have confirmed shift."""

import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    # Seed two workers for the shift_workers reference
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (1, 'Anna', 'Kowalska', 'AK', 'AK', 1)"
    )
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (2, 'Maria', 'Wojcik', 'MW', 'MW', 1)"
    )
    # Seed an MBR template + open EBR for the save_entry test
    from datetime import datetime
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia) VALUES (?, 1, 'active', '[]', '{}', 'test', ?)",
        ("TestProduct", now),
    )
    mbr_id = conn.execute(
        "SELECT mbr_id FROM mbr_templates WHERE produkt='TestProduct'"
    ).fetchone()["mbr_id"]
    conn.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, typ) "
        "VALUES (?, ?, ?, ?, 'open', 'szarza')",
        (mbr_id, "TestProduct__1", "1/2026", now),
    )
    conn.commit()
    yield conn
    conn.close()


def _make_client(monkeypatch, db, rola="lab", shift_workers=None):
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
        sess["user"] = {"login": "shared_lab", "rola": rola}
        if shift_workers is not None:
            sess["shift_workers"] = shift_workers
    return client


# ---------- save_entry shift enforcement ----------

def test_save_entry_laborant_empty_shift_returns_400(monkeypatch, db):
    """Laborant POST /laborant/ebr/<id>/save with no shift → 400 shift_required,
    no row written to ebr_wyniki."""
    client = _make_client(monkeypatch, db, rola="lab", shift_workers=[])
    resp = client.post(
        "/laborant/ebr/1/save",
        json={"sekcja": "analiza", "values": {"sm": 87}},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body == {"error": "shift_required"}

    # No row in ebr_wyniki
    count = db.execute("SELECT COUNT(*) FROM ebr_wyniki").fetchone()[0]
    assert count == 0


def test_save_entry_laborant_with_shift_succeeds(monkeypatch, db):
    """Laborant with confirmed shift can save normally."""
    client = _make_client(monkeypatch, db, rola="lab", shift_workers=[1, 2])
    resp = client.post(
        "/laborant/ebr/1/save",
        json={"sekcja": "analiza", "values": {"sm": 87}},
    )
    assert resp.status_code == 200


# ---------- save_uwagi shift enforcement (symmetric) ----------

def test_save_uwagi_laborant_empty_shift_returns_400(monkeypatch, db):
    client = _make_client(monkeypatch, db, rola="lab", shift_workers=[])
    resp = client.put("/api/ebr/1/uwagi", json={"tekst": "Test note"})
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "shift_required"}
    # No row in ebr_uwagi_history
    count = db.execute("SELECT COUNT(*) FROM ebr_uwagi_history").fetchone()[0]
    assert count == 0


# ---------- non-laborant roles still fall back to login ----------

def test_save_entry_admin_empty_shift_succeeds(monkeypatch, db):
    """Admin/technolog/laborant_kj/laborant_coa keep the login fallback when
    shift is empty — only role='lab' is enforced."""
    client = _make_client(monkeypatch, db, rola="admin", shift_workers=[])
    resp = client.post(
        "/laborant/ebr/1/save",
        json={"sekcja": "analiza", "values": {"sm": 87}},
    )
    assert resp.status_code == 200
