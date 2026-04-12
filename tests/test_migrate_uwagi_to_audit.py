"""Tests for scripts/migrate_uwagi_to_audit.py"""

import json
import sqlite3
import pytest

from mbr.models import init_mbr_tables


def _make_db_with_uwagi_history(rows=None):
    """In-memory DB with ebr_uwagi_history + audit_log tables."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_mbr_tables(db)
    # Seed a batch so entity_label can resolve
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia) VALUES ('TestP', 1, 'active', '[]', '{}', 'test', '2026-04-01')"
    )
    mbr_id = db.execute("SELECT mbr_id FROM mbr_templates").fetchone()["mbr_id"]
    db.execute(
        "INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start, status, typ) "
        "VALUES (1, ?, 'TestP__1', '1/2026', '2026-04-01', 'open', 'szarza')",
        (mbr_id,),
    )
    # Seed workers for author resolution
    db.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname) VALUES (1, 'Anna', 'Kowalska', 'AK', 'AK')"
    )
    for r in rows or []:
        db.execute(
            "INSERT INTO ebr_uwagi_history (ebr_id, tekst, action, autor, dt) VALUES (?, ?, ?, ?, ?)",
            r,
        )
    db.commit()
    return db


def test_migrate_uwagi_empty_table():
    db = _make_db_with_uwagi_history()
    from scripts.migrate_uwagi_to_audit import migrate_uwagi
    summary = migrate_uwagi(db)
    assert summary["migrated"] == 0


def test_migrate_uwagi_backfills_rows():
    db = _make_db_with_uwagi_history(rows=[
        (1, "stary tekst", "create", "AK", "2026-04-01T10:00:00"),
        (1, "stary tekst", "update", "AK", "2026-04-01T11:00:00"),
    ])
    from scripts.migrate_uwagi_to_audit import migrate_uwagi
    summary = migrate_uwagi(db)
    assert summary["migrated"] == 2

    rows = db.execute(
        "SELECT event_type, entity_type, entity_id, payload_json FROM audit_log "
        "WHERE event_type = 'ebr.uwagi.updated' ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["entity_type"] == "ebr"
    assert rows[0]["entity_id"] == 1

    payload = json.loads(rows[0]["payload_json"])
    assert payload["action"] == "create"
    assert payload["tekst"] == "stary tekst"


def test_migrate_uwagi_idempotent():
    db = _make_db_with_uwagi_history(rows=[
        (1, "tekst", "create", "AK", "2026-04-01T10:00:00"),
    ])
    from scripts.migrate_uwagi_to_audit import migrate_uwagi
    migrate_uwagi(db)
    summary2 = migrate_uwagi(db)
    assert summary2["migrated"] == 0
    count = db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE event_type='ebr.uwagi.updated'"
    ).fetchone()[0]
    assert count == 1  # only from first run
