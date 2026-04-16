"""Migrate parameter binding data from parametry_etapy + etap_parametry into the
extended produkt_etap_limity table, and cert metadata into parametry_cert.

Does NOT drop the legacy tables — that happens in a later PR after application
code is refactored to read from the new SSOT.

Usage:
    python -m scripts.migrate_parametry_ssot [--db PATH] [--dry-run] [--verify-only] [--force]
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


MIGRATION_NAME = "parametry_ssot_v1"


def backup(db_path: str) -> str:
    """Copy DB file next to original with timestamped suffix. Return backup path."""
    src = Path(db_path)
    if not src.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")
    dst = src.with_suffix(src.suffix + f".bak-pre-parametry-ssot")
    shutil.copy2(src, dst)
    return str(dst)


def already_applied(db: sqlite3.Connection) -> bool:
    """Check if migration has run before using _migrations marker table."""
    db.execute(
        "CREATE TABLE IF NOT EXISTS _migrations ("
        " name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    row = db.execute(
        "SELECT 1 FROM _migrations WHERE name=?", (MIGRATION_NAME,)
    ).fetchone()
    return row is not None


def mark_applied(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO _migrations (name, applied_at) VALUES (?, ?)",
        (MIGRATION_NAME, datetime.now().isoformat(timespec="seconds")),
    )


def preflight(db: sqlite3.Connection) -> list[str]:
    """Return list of blocker messages. Empty list = OK to proceed."""
    return []  # filled in later tasks


def postflight(db: sqlite3.Connection) -> list[str]:
    """Return list of post-migration validation errors. Empty list = OK."""
    return []  # filled in later tasks


def migrate(db: sqlite3.Connection, dry_run: bool = False) -> None:
    """Run the full migration inside a single transaction."""
    if already_applied(db):
        print(f"Migration {MIGRATION_NAME} already applied — skipping.")
        return

    blockers = preflight(db)
    if blockers:
        print("Pre-flight checks failed:", file=sys.stderr)
        for b in blockers:
            print(f"  - {b}", file=sys.stderr)
        raise SystemExit(1)

    if dry_run:
        print("Dry run — no changes will be committed.")

    # Migration steps filled in by later tasks.

    errors = postflight(db)
    if errors:
        print("Post-flight validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        raise SystemExit(2)

    if dry_run:
        db.rollback()
        print("Dry run complete — rolled back.")
    else:
        mark_applied(db)
        db.commit()
        print(f"Migration {MIGRATION_NAME} committed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/batch_db.sqlite")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run migration inside a transaction and roll back at the end.")
    parser.add_argument("--verify-only", action="store_true",
                        help="Run postflight only without altering data.")
    parser.add_argument("--force", action="store_true",
                        help="Re-run even if _migrations marker is present.")
    args = parser.parse_args()

    if not args.dry_run and not args.verify_only:
        bkp = backup(args.db)
        print(f"Backup: {bkp}")

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")

    try:
        if args.verify_only:
            errors = postflight(db)
            if errors:
                for e in errors:
                    print(f"  - {e}")
                raise SystemExit(2)
            print("Verification OK.")
        else:
            if args.force:
                db.execute("DELETE FROM _migrations WHERE name=?", (MIGRATION_NAME,))
            migrate(db, dry_run=args.dry_run)
    finally:
        db.close()


if __name__ == "__main__":
    main()
