"""
Migrate standaryzacja gate conditions from 'between 0..9999' to 'w_limicie'.

The 'between' operator checked against hardcoded 0..9999 (always passes).
The 'w_limicie' operator checks the w_limicie flag set by save_pomiar
against product-specific limits in produkt_etap_limity.

Run: python -m scripts.migrate_standaryzacja_gate
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mbr.db import get_db


def migrate(db: sqlite3.Connection) -> int:
    stand = db.execute(
        "SELECT id FROM etapy_analityczne WHERE kod = 'standaryzacja'"
    ).fetchone()
    if not stand:
        print("Standaryzacja etap not found — skipping.")
        return 0

    etap_id = stand[0]
    rows = db.execute(
        "SELECT id, parametr_id, operator, wartosc, wartosc_max FROM etap_warunki WHERE etap_id = ?",
        (etap_id,),
    ).fetchall()

    updated = 0
    for r in rows:
        if r["operator"] == "between" and r["wartosc"] == 0 and r["wartosc_max"] == 9999:
            db.execute(
                "UPDATE etap_warunki SET operator = 'w_limicie', wartosc = NULL, wartosc_max = NULL WHERE id = ?",
                (r["id"],),
            )
            updated += 1
            print(f"  Updated warunek id={r['id']} parametr_id={r['parametr_id']}: between 0..9999 → w_limicie")

    db.commit()
    print(f"Migrated {updated} standaryzacja gate conditions.")
    return updated


if __name__ == "__main__":
    db = get_db()
    try:
        migrate(db)
    finally:
        db.close()
