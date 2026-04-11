"""Migration: add uwagi_koncowe column + ebr_uwagi_history table.

Idempotent — safe to run multiple times.

Usage:
    python migrate_uwagi_koncowe.py
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "batch_db.sqlite"


def main():
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    cols = [r[1] for r in conn.execute("PRAGMA table_info(ebr_batches)").fetchall()]
    if "uwagi_koncowe" not in cols:
        conn.execute("ALTER TABLE ebr_batches ADD COLUMN uwagi_koncowe TEXT")
        print("Added uwagi_koncowe column to ebr_batches")
    else:
        print("uwagi_koncowe column already exists")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS ebr_uwagi_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ebr_id     INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
            tekst      TEXT,
            action     TEXT NOT NULL CHECK(action IN ('create', 'update', 'delete')),
            autor      TEXT NOT NULL,
            dt         TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ebr_uwagi_history_ebr "
        "ON ebr_uwagi_history(ebr_id, dt DESC)"
    )
    conn.commit()
    conn.close()
    print("OK — uwagi_koncowe migration applied")


if __name__ == "__main__":
    main()
