"""Tests for scripts/migrate_audit_log_v2.py"""

import json
import sqlite3

from scripts.migrate_audit_log_v2 import migrate


def _make_db_with_old_schema(rows=None):
    """Build in-memory DB matching pre-migration state: old audit_log + workers."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("""
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dt TEXT NOT NULL,
            tabela TEXT NOT NULL,
            rekord_id INTEGER NOT NULL,
            pole TEXT NOT NULL,
            stara_wartosc TEXT,
            nowa_wartosc TEXT,
            zmienil TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            imie TEXT, nazwisko TEXT, nickname TEXT, inicjaly TEXT,
            login TEXT, rola TEXT
        )
    """)
    for r in rows or []:
        db.execute(
            "INSERT INTO audit_log (dt, tabela, rekord_id, pole, stara_wartosc, nowa_wartosc, zmienil) VALUES (?,?,?,?,?,?,?)",
            r,
        )
    db.commit()
    return db


def test_migrate_fresh_db_no_old_table_is_noop():
    """Running migration on DB without audit_log (truly fresh) is a no-op that exits cleanly."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    summary = migrate(db)
    assert summary["backfilled"] == 0
    assert summary["renamed"] is False


def test_migrate_old_audit_log_backfills_rows():
    """Legacy rows migrate as event_type='legacy.field_change'."""
    db = _make_db_with_old_schema(rows=[
        ("2026-04-01T10:00:00", "ebr_wyniki", 42, "temperatura", "85", "87", "AK"),
        ("2026-04-01T11:00:00", "ebr_stages", 17, "status", "open", "done", "MW"),
    ])
    db.execute(
        "INSERT INTO workers (id, imie, nazwisko, nickname, inicjaly, rola) VALUES (1,'Anna','Kowalska','AK','AK','laborant')"
    )
    db.execute(
        "INSERT INTO workers (id, imie, nazwisko, nickname, inicjaly, rola) VALUES (2,'Maria','Wójcik','MW','MW','laborant')"
    )
    db.commit()

    summary = migrate(db)

    assert summary["renamed"] is True
    assert summary["backfilled"] == 2

    new_rows = db.execute(
        "SELECT event_type, entity_type, entity_id, diff_json FROM audit_log ORDER BY id"
    ).fetchall()
    assert len(new_rows) == 2
    assert new_rows[0]["event_type"] == "legacy.field_change"
    assert new_rows[0]["entity_type"] == "ebr_wyniki"
    assert new_rows[0]["entity_id"] == 42
    diff = json.loads(new_rows[0]["diff_json"])
    assert diff == [{"pole": "temperatura", "stara": "85", "nowa": "87"}]

    actors = db.execute(
        "SELECT audit_id, worker_id, actor_login, actor_rola FROM audit_log_actors ORDER BY audit_id"
    ).fetchall()
    assert len(actors) == 2
    assert actors[0]["worker_id"] == 1
    assert actors[0]["actor_login"] == "AK"
    assert actors[0]["actor_rola"] == "laborant"


def test_migrate_unknown_zmienil_stores_null_worker_id():
    """When `zmienil` can't be resolved to a worker, store NULL worker_id + 'unknown' rola."""
    db = _make_db_with_old_schema(rows=[
        ("2026-04-01T10:00:00", "x", 1, "pole", "a", "b", "ghost_user"),
    ])
    migrate(db)
    actor = db.execute("SELECT worker_id, actor_login, actor_rola FROM audit_log_actors").fetchone()
    assert actor["worker_id"] is None
    assert actor["actor_login"] == "ghost_user"
    assert actor["actor_rola"] == "unknown"


def test_migrate_is_idempotent():
    """Running twice is a no-op on the second run."""
    db = _make_db_with_old_schema(rows=[
        ("2026-04-01T10:00:00", "x", 1, "p", "a", "b", "AK"),
    ])
    migrate(db)
    summary_second = migrate(db)
    assert summary_second["skipped_already_migrated"] is True
    assert summary_second["backfilled"] == 0
    count = db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    assert count == 1


def test_migrate_recovers_from_wedged_state():
    """Simulate a crash mid-migration: audit_log_v1 exists, audit_log doesn't.

    migrate() should detect this and complete the backfill anyway."""
    db = _make_db_with_old_schema(rows=[
        ("2026-04-01T10:00:00", "ebr_wyniki", 42, "temperatura", "85", "87", "AK"),
        ("2026-04-01T11:00:00", "ebr_stages", 17, "status", "open", "done", "MW"),
    ])
    db.execute(
        "INSERT INTO workers (id, imie, nazwisko, nickname, inicjaly, rola) VALUES (1,'Anna','Kowalska','AK','AK','laborant')"
    )
    db.commit()

    # Simulate crashed state: rename old table, but DO NOT create new
    # audit_log, audit_log_actors, or indexes — as would happen if the
    # script crashed between ALTER TABLE and the final commit.
    db.execute("ALTER TABLE audit_log RENAME TO audit_log_v1")
    db.commit()

    # Sanity: we are in the wedged state we intend to test.
    assert db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'"
    ).fetchone() is None
    assert db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log_v1'"
    ).fetchone() is not None

    summary = migrate(db)

    assert summary["recovered"] is True
    assert summary["backfilled"] == 2

    # New table exists, has both rows, and new columns are present.
    cols = [r[1] for r in db.execute("PRAGMA table_info(audit_log)").fetchall()]
    assert "event_type" in cols

    new_rows = db.execute(
        "SELECT event_type, entity_type, entity_id FROM audit_log ORDER BY id"
    ).fetchall()
    assert len(new_rows) == 2
    assert new_rows[0]["event_type"] == "legacy.field_change"
    assert new_rows[0]["entity_type"] == "ebr_wyniki"

    actors = db.execute(
        "SELECT worker_id, actor_login, actor_rola FROM audit_log_actors ORDER BY audit_id"
    ).fetchall()
    assert len(actors) == 2
    assert actors[0]["worker_id"] == 1
    assert actors[0]["actor_rola"] == "laborant"
    # MW has no workers row → unresolved
    assert actors[1]["worker_id"] is None
    assert actors[1]["actor_login"] == "MW"
    assert actors[1]["actor_rola"] == "unknown"


def test_migrate_without_workers_table_stores_unknown_rola():
    """When workers table doesn't exist, zmienil becomes actor_login with 'unknown' rola."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dt TEXT NOT NULL, tabela TEXT NOT NULL, rekord_id INTEGER NOT NULL,
            pole TEXT NOT NULL, stara_wartosc TEXT, nowa_wartosc TEXT,
            zmienil TEXT NOT NULL
        )
    """)
    db.execute(
        "INSERT INTO audit_log (dt,tabela,rekord_id,pole,stara_wartosc,nowa_wartosc,zmienil) VALUES (?,?,?,?,?,?,?)",
        ("2026-04-01T10:00", "x", 1, "p", "a", "b", "AK"),
    )
    db.commit()

    summary = migrate(db)
    assert summary["backfilled"] == 1

    actor = db.execute(
        "SELECT worker_id, actor_login, actor_rola FROM audit_log_actors"
    ).fetchone()
    assert actor["worker_id"] is None
    assert actor["actor_login"] == "AK"
    assert actor["actor_rola"] == "unknown"


def test_migrate_dry_run_does_not_mutate():
    """--dry-run reports what would happen without changing the DB."""
    db = _make_db_with_old_schema(rows=[
        ("2026-04-01T10:00:00", "x", 1, "p", "a", "b", "AK"),
    ])
    summary = migrate(db, dry_run=True)
    assert summary["backfilled"] == 1
    assert db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'"
    ).fetchone() is not None
    assert db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log_v1'"
    ).fetchone() is None
    cols = [r[1] for r in db.execute("PRAGMA table_info(audit_log)").fetchall()]
    assert "event_type" not in cols
