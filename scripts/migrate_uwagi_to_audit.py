"""
migrate_uwagi_to_audit.py — one-time migration: ebr_uwagi_history → audit_log.

Backfills each ebr_uwagi_history row as an audit_log entry with
event_type='ebr.uwagi.updated', entity_type='ebr', payload={action, tekst}.

Idempotent: skips rows that already have a matching audit_log entry
(matched by entity_id + dt + event_type).

Usage:
    python scripts/migrate_uwagi_to_audit.py --db data/batch_db.sqlite [--dry-run]
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def _resolve_worker(db, autor: str):
    """Resolve autor string to (worker_id, actor_login, actor_rola)."""
    if not autor:
        return (None, "unknown", "unknown")
    row = db.execute(
        "SELECT id FROM workers WHERE inicjaly=? OR nickname=? LIMIT 1",
        (autor, autor),
    ).fetchone()
    if row:
        return (row[0], autor, "laborant")
    return (None, autor, "unknown")


def _get_entity_label(db, ebr_id: int) -> str:
    """Resolve batch label for entity_label."""
    row = db.execute(
        "SELECT b.batch_id, b.nr_partii, m.produkt "
        "FROM ebr_batches b JOIN mbr_templates m ON b.mbr_id = m.mbr_id "
        "WHERE b.ebr_id = ?",
        (ebr_id,),
    ).fetchone()
    if row:
        return f"{row['produkt']} {row['nr_partii']}"
    return None


def migrate_uwagi(db: sqlite3.Connection, dry_run: bool = False) -> dict:
    summary = {"migrated": 0, "skipped": 0}

    history_rows = db.execute(
        "SELECT id, ebr_id, tekst, action, autor, dt FROM ebr_uwagi_history ORDER BY id"
    ).fetchall()

    for h in history_rows:
        # Idempotency check
        existing = db.execute(
            "SELECT 1 FROM audit_log WHERE event_type='ebr.uwagi.updated' "
            "AND entity_id=? AND dt=?",
            (h["ebr_id"], h["dt"]),
        ).fetchone()
        if existing:
            summary["skipped"] += 1
            continue

        if dry_run:
            summary["migrated"] += 1
            continue

        entity_label = _get_entity_label(db, h["ebr_id"])

        cur = db.execute(
            """INSERT INTO audit_log
               (dt, event_type, entity_type, entity_id, entity_label,
                payload_json, result)
               VALUES (?, 'ebr.uwagi.updated', 'ebr', ?, ?, ?, 'ok')""",
            (
                h["dt"],
                h["ebr_id"],
                entity_label,
                json.dumps({"action": h["action"], "tekst": h["tekst"]}, ensure_ascii=False),
            ),
        )
        worker_id, actor_login, actor_rola = _resolve_worker(db, h["autor"])
        db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) "
            "VALUES (?, ?, ?, ?)",
            (cur.lastrowid, worker_id, actor_login, actor_rola),
        )
        summary["migrated"] += 1

    if not dry_run and summary["migrated"] > 0:
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
        summary = migrate_uwagi(db, dry_run=args.dry_run)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()

    print(f"Uwagi migration: {summary}")
    if args.dry_run:
        print("(dry-run)")


if __name__ == "__main__":
    main()
