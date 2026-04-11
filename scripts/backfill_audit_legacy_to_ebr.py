"""
backfill_audit_legacy_to_ebr.py — one-time fixup for Phase 1 legacy entries.

Phase 1 migrated the old audit_log into the new schema preserving the original
'tabela' / 'rekord_id' columns as entity_type='ebr_wyniki' / entity_id=<wynik_id>.
That points to a CHILD row (ebr_wyniki), not to the parent batch (ebr_batches),
so the UI can't link these entries to a specific szarża.

This script JOINs through ebr_wyniki → ebr_batches and rewrites:
  entity_type   'ebr_wyniki'  → 'ebr'
  entity_id     <wynik_id>    → <ebr_id>
  entity_label   NULL         → '<produkt> <nr_partii>'  (e.g. 'Chegina_K40GLOL 2/2026')

Idempotent: only touches rows where event_type='legacy.field_change' AND
entity_label IS NULL. Re-running is a no-op.

For wyniki rows that no longer exist (deleted before migration), the entry is
marked entity_label='(historyczny — wynik usunięty)' so admin sees it as a
known-orphan record. entity_type stays 'ebr_wyniki'.

Usage:
    python scripts/backfill_audit_legacy_to_ebr.py --db data/batch_db.sqlite [--dry-run]
"""

import argparse
import sqlite3
import sys
from pathlib import Path


_LEGACY_PREDICATE = (
    "event_type = 'legacy.field_change' "
    "AND entity_type = 'ebr_wyniki' "
    "AND entity_label IS NULL"
)


def backfill(db: sqlite3.Connection, dry_run: bool = False) -> dict:
    """Resolve legacy ebr_wyniki entries to their parent batch.

    Returns a summary dict with counts of resolved/orphaned/skipped rows.
    """
    summary = {"resolved": 0, "orphaned": 0, "scanned": 0}

    legacy_rows = db.execute(
        f"SELECT id, entity_id FROM audit_log WHERE {_LEGACY_PREDICATE}"
    ).fetchall()
    summary["scanned"] = len(legacy_rows)

    for row in legacy_rows:
        audit_id = row["id"]
        wynik_id = row["entity_id"]

        join_row = db.execute(
            """
            SELECT b.ebr_id, b.batch_id, b.nr_partii, m.produkt
            FROM ebr_wyniki w
            JOIN ebr_batches b ON w.ebr_id = b.ebr_id
            JOIN mbr_templates m ON b.mbr_id = m.mbr_id
            WHERE w.wynik_id = ?
            """,
            (wynik_id,),
        ).fetchone()

        if join_row:
            label = f"{join_row['produkt']} {join_row['nr_partii']}"
            if not dry_run:
                db.execute(
                    """
                    UPDATE audit_log
                    SET entity_type = 'ebr',
                        entity_id   = ?,
                        entity_label = ?
                    WHERE id = ?
                    """,
                    (join_row["ebr_id"], label, audit_id),
                )
            summary["resolved"] += 1
        else:
            if not dry_run:
                db.execute(
                    "UPDATE audit_log SET entity_label = ? WHERE id = ?",
                    ("(historyczny — wynik usunięty)", audit_id),
                )
            summary["orphaned"] += 1

    if not dry_run:
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
        summary = backfill(db, dry_run=args.dry_run)
    except Exception as e:
        print(f"ERROR: backfill failed: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()

    print(f"Backfill summary: {summary}")
    if args.dry_run:
        print("(dry-run — no changes committed)")


if __name__ == "__main__":
    main()
