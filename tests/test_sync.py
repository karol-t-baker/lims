"""tests/test_sync.py — Tests for index-based sync."""

import json as json_mod
import sqlite3
from unittest.mock import patch

import pytest

from mbr.db import get_db
from mbr.models import init_mbr_tables
from mbr.laborant.models import complete_ebr, save_wyniki, get_ebr
from mbr.app import create_app


@pytest.fixture
def db(tmp_path):
    """Fresh in-memory-like DB with all MBR tables."""
    db_path = tmp_path / "test.sqlite"
    with patch("mbr.db.DB_PATH", db_path):
        conn = get_db()
        init_mbr_tables(conn)
        yield conn
        conn.close()


def _create_batch(db, batch_id="TEST__1_2026", nr_partii="1/2026", mbr_id=1):
    """Helper: create an open batch, return ebr_id."""
    db.execute(
        "INSERT OR IGNORE INTO mbr_templates (mbr_id, produkt, wersja, status, parametry_lab, dt_utworzenia) VALUES (?,?,?,?,?,datetime('now'))",
        (mbr_id, "Test", 1, "active", "{}"),
    )
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status) VALUES (?,?,?,datetime('now'),'open')",
        (mbr_id, batch_id, nr_partii),
    )
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_complete_ebr_assigns_sync_seq(db):
    """Completing a batch assigns a monotonically increasing sync_seq."""
    id1 = _create_batch(db, "A__1", "1/2026")
    id2 = _create_batch(db, "B__2", "2/2026")

    complete_ebr(db, id1)
    complete_ebr(db, id2)

    seq1 = db.execute("SELECT sync_seq FROM ebr_batches WHERE ebr_id=?", (id1,)).fetchone()[0]
    seq2 = db.execute("SELECT sync_seq FROM ebr_batches WHERE ebr_id=?", (id2,)).fetchone()[0]

    assert seq1 is not None
    assert seq2 is not None
    assert seq2 > seq1


def test_sync_seq_column_exists(db):
    """ebr_batches has sync_seq INTEGER column after init."""
    cols = {r[1]: r[2] for r in db.execute("PRAGMA table_info(ebr_batches)").fetchall()}
    assert "sync_seq" in cols
    assert cols["sync_seq"] == "INTEGER"


def test_save_wyniki_bumps_sync_seq_on_completed(db):
    """Changing wyniki on a completed batch bumps its sync_seq."""
    ebr_id = _create_batch(db, "C__3", "3/2026")
    complete_ebr(db, ebr_id)

    old_seq = db.execute("SELECT sync_seq FROM ebr_batches WHERE ebr_id=?", (ebr_id,)).fetchone()[0]

    # Simulate saving a result
    ebr = get_ebr(db, ebr_id)
    save_wyniki(db, ebr_id, "analiza_koncowa", {
        "ph": {"wartosc": "7.5", "tag": "ph", "min": 6.0, "max": 9.0}
    }, "test_user", ebr=ebr)

    new_seq = db.execute("SELECT sync_seq FROM ebr_batches WHERE ebr_id=?", (ebr_id,)).fetchone()[0]
    assert new_seq > old_seq


# ---------------------------------------------------------------------------
# /api/completed endpoint tests
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    """Flask test client with fresh DB."""
    db_path = tmp_path / "test.sqlite"
    with patch("mbr.db.DB_PATH", db_path):
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c


def test_api_completed_returns_delta(client, tmp_path):
    """GET /api/completed?since=0 returns all completed batches."""
    db_path = tmp_path / "test.sqlite"
    with patch("mbr.db.DB_PATH", db_path):
        from mbr.db import get_db
        from mbr.models import init_mbr_tables
        conn = get_db()
        init_mbr_tables(conn)
        conn.execute(
            "INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, parametry_lab, dt_utworzenia) VALUES (1,'Test',1,'active','{}',datetime('now'))"
        )
        conn.execute(
            "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, sync_seq) VALUES (1,'T__1','1/2026',datetime('now'),'completed',1)"
        )
        conn.execute(
            "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (1,'analiza_koncowa','ph','ph',7.2,1,datetime('now'),'test')"
        )
        conn.commit()
        conn.close()

        resp = client.get("/api/completed?since=0")
        data = resp.get_json()

        assert data["ok"] is True
        assert data["max_seq"] == 1
        assert len(data["batches"]) == 1
        assert data["batches"][0]["batch_id"] == "T__1"
        assert len(data["wyniki"]) >= 1


def test_api_completed_skips_old(client, tmp_path):
    """GET /api/completed?since=1 skips batches with sync_seq <= 1."""
    db_path = tmp_path / "test.sqlite"
    with patch("mbr.db.DB_PATH", db_path):
        from mbr.db import get_db
        from mbr.models import init_mbr_tables
        conn = get_db()
        init_mbr_tables(conn)
        conn.execute(
            "INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, parametry_lab, dt_utworzenia) VALUES (1,'Test',1,'active','{}',datetime('now'))"
        )
        conn.execute(
            "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, sync_seq) VALUES (1,'T__1','1/2026',datetime('now'),'completed',1)"
        )
        conn.execute(
            "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, sync_seq) VALUES (1,'T__2','2/2026',datetime('now'),'completed',2)"
        )
        conn.commit()
        conn.close()

        resp = client.get("/api/completed?since=1")
        data = resp.get_json()

        assert len(data["batches"]) == 1
        assert data["batches"][0]["batch_id"] == "T__2"
        assert data["max_seq"] == 2
