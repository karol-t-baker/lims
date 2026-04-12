"""Add precision column to parametry_etapy table.

Run once: python scripts/migrate_precision_etapy.py
"""

import sqlite3
import sys
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "batch_db.sqlite")


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"DB not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    cols = [r["name"] for r in conn.execute("PRAGMA table_info(parametry_etapy)")]
    if "precision" in cols:
        print("Column 'precision' already exists in parametry_etapy. Nothing to do.")
        conn.close()
        return

    conn.execute("ALTER TABLE parametry_etapy ADD COLUMN precision INTEGER")
    conn.commit()
    print("Added 'precision' column to parametry_etapy.")
    conn.close()


if __name__ == "__main__":
    migrate()
