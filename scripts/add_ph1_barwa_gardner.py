"""
Add pH 1% and Barwa Gardner parameters to parametry_analityczne.

Run: python -m scripts.add_ph1_barwa_gardner
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mbr.db import get_db


def migrate(db: sqlite3.Connection) -> int:
    added = 0
    for kod, label, skrot, prec in [
        ("ph_1proc", "pH roztworu 1%", "pH 1%", 2),
        ("barwa_gardner", "Barwa wg Gardnera", "Barwa G", 0),
    ]:
        existing = db.execute(
            "SELECT id FROM parametry_analityczne WHERE kod = ?", (kod,)
        ).fetchone()
        if existing:
            print(f"  {kod} already exists (id={existing[0]}), skipping.")
            continue
        db.execute(
            """INSERT INTO parametry_analityczne (kod, label, skrot, typ, precision, aktywny)
               VALUES (?, ?, ?, 'bezposredni', ?, 1)""",
            (kod, label, skrot, prec),
        )
        added += 1
        print(f"  Added: {kod} ({label})")

    db.commit()
    print(f"Done. Added {added} parameters.")
    return added


if __name__ == "__main__":
    db = get_db()
    try:
        migrate(db)
    finally:
        db.close()
