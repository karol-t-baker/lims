#!/usr/bin/env python3
"""One-time migration: rename target -> spec_value in etap_parametry and produkt_etap_limity."""
import sqlite3, sys, os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "batch_db.sqlite")

def migrate():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    for table in ("etap_parametry", "produkt_etap_limity"):
        info = db.execute(f"PRAGMA table_info({table})").fetchall()
        col_names = [r["name"] for r in info]
        if "target" in col_names and "spec_value" not in col_names:
            db.execute(f"ALTER TABLE {table} RENAME COLUMN target TO spec_value")
            print(f"Renamed target -> spec_value in {table}")
        elif "spec_value" in col_names:
            print(f"{table}: already has spec_value, skipping")
        else:
            print(f"{table}: no target column found, skipping")
    db.commit()
    db.close()

if __name__ == "__main__":
    migrate()
