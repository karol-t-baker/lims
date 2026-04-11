"""
migrate_audit_log_v2.py — one-time migration for existing installs.

Transforms legacy audit_log (dt, tabela, rekord_id, pole, stara_wartosc,
nowa_wartosc, zmienil) into the new event-based schema + audit_log_actors
junction. Idempotent — rerunning is safe.

Steps:
  1. If audit_log has NEW columns already (event_type exists), exit — already migrated.
  2. Else rename old table to audit_log_v1.
  3. Create new audit_log + audit_log_actors + indexes.
  4. Backfill audit_log_v1 -> audit_log as event_type='legacy.field_change',
     resolving `zmienil` string -> worker_id when possible (JOIN on workers.inicjaly
     or workers.nickname or workers.login).
  5. Verify counts match; leave audit_log_v1 in place for rollback (drop in Phase 7).

Usage:
    python scripts/migrate_audit_log_v2.py --db data/batch_db.sqlite [--dry-run]
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path


_NEW_AUDIT_LOG_DDL = """
CREATE TABLE audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    dt              TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    entity_type     TEXT,
    entity_id       INTEGER,
    entity_label    TEXT,
    diff_json       TEXT,
    payload_json    TEXT,
    context_json    TEXT,
    request_id      TEXT,
    ip              TEXT,
    user_agent      TEXT,
    result          TEXT NOT NULL DEFAULT 'ok'
)
"""

_NEW_AUDIT_ACTORS_DDL = """
CREATE TABLE audit_log_actors (
    audit_id        INTEGER NOT NULL REFERENCES audit_log(id) ON DELETE CASCADE,
    worker_id       INTEGER,
    actor_login     TEXT NOT NULL,
    actor_rola      TEXT NOT NULL,
    PRIMARY KEY (audit_id, actor_login)
)
"""

_INDEXES = [
    "CREATE INDEX idx_audit_log_dt ON audit_log(dt DESC)",
    "CREATE INDEX idx_audit_log_entity ON audit_log(entity_type, entity_id)",
    "CREATE INDEX idx_audit_log_event_type ON audit_log(event_type)",
    "CREATE INDEX idx_audit_log_request ON audit_log(request_id)",
    "CREATE INDEX idx_audit_actors_worker ON audit_log_actors(worker_id)",
]


def _table_exists(db: sqlite3.Connection, name: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _has_new_columns(db: sqlite3.Connection) -> bool:
    """Return True if audit_log already has the new 'event_type' column."""
    cols = [r[1] for r in db.execute("PRAGMA table_info(audit_log)").fetchall()]
    return "event_type" in cols


def _resolve_worker(db: sqlite3.Connection, zmienil: str):
    """Try to find workers.id for a legacy `zmienil` string.
    Returns (worker_id or None, actor_login, actor_rola)."""
    if not _table_exists(db, "workers"):
        return (None, zmienil, "unknown")
    row = db.execute(
        """SELECT id, COALESCE(rola, 'unknown') AS rola FROM workers
           WHERE inicjaly=? OR nickname=? OR login=?
           LIMIT 1""",
        (zmienil, zmienil, zmienil),
    ).fetchone()
    if row:
        return (row[0], zmienil, row[1])
    return (None, zmienil, "unknown")


def migrate(db: sqlite3.Connection, dry_run: bool = False) -> dict:
    summary = {"renamed": False, "backfilled": 0, "skipped_already_migrated": False}

    if not _table_exists(db, "audit_log"):
        return summary

    if _has_new_columns(db):
        summary["skipped_already_migrated"] = True
        return summary

    if dry_run:
        count = db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        summary["backfilled"] = count
        summary["renamed"] = True  # would be
        return summary

    db.execute("ALTER TABLE audit_log RENAME TO audit_log_v1")
    summary["renamed"] = True

    db.execute(_NEW_AUDIT_LOG_DDL)
    db.execute(_NEW_AUDIT_ACTORS_DDL)
    for ddl in _INDEXES:
        db.execute(ddl)

    old_rows = db.execute(
        "SELECT id, dt, tabela, rekord_id, pole, stara_wartosc, nowa_wartosc, zmienil FROM audit_log_v1"
    ).fetchall()

    for old in old_rows:
        diff = [{"pole": old[4], "stara": old[5], "nowa": old[6]}]
        cur = db.execute(
            """INSERT INTO audit_log
               (dt, event_type, entity_type, entity_id, diff_json, result)
               VALUES (?, 'legacy.field_change', ?, ?, ?, 'ok')""",
            (old[1], old[2], old[3], json.dumps(diff, ensure_ascii=False)),
        )
        new_id = cur.lastrowid
        worker_id, actor_login, actor_rola = _resolve_worker(db, old[7])
        db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, ?, ?, ?)",
            (new_id, worker_id, actor_login, actor_rola),
        )
        summary["backfilled"] += 1

    old_count = db.execute("SELECT COUNT(*) FROM audit_log_v1").fetchone()[0]
    new_count = db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    if old_count != new_count:
        raise RuntimeError(
            f"Backfill count mismatch: old={old_count}, new={new_count}"
        )

    db.commit()
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/batch_db.sqlite")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: {db_path} not found", file=sys.stderr)
        sys.exit(1)

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        summary = migrate(db, dry_run=args.dry_run)
    finally:
        db.close()

    print(f"Migration summary: {summary}")
    if args.dry_run:
        print("(dry-run — no changes committed)")


if __name__ == "__main__":
    main()
