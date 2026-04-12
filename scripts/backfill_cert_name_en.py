"""Backfill name_en + method for parametry_cert from extraction report + cross-fill.

Idempotent — only updates rows where name_en IS NULL or empty.
"""
import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "data" / "batch_db.sqlite"
REPORT = BASE / "data" / "cert_extraction_report.json"

def backfill(db_path=None):
    db_path = db_path or DB
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row

    kod_lookup = {}

    # 1. From extraction report
    if REPORT.exists():
        with open(REPORT) as f:
            report = json.load(f)
        for pdata in report.get("products", {}).values():
            for p in pdata.get("parameters", []):
                kod = p.get("matched_kod")
                if kod and p.get("name_en") and kod not in kod_lookup:
                    kod_lookup[kod] = {"name_en": p["name_en"], "method": p.get("method", "")}

    # 2. Cross-fill from DB (products that already have name_en)
    for row in db.execute("""
        SELECT pa.kod, pc.name_en, pc.method
        FROM parametry_cert pc
        JOIN parametry_analityczne pa ON pa.id = pc.parametr_id
        WHERE pc.name_en IS NOT NULL AND pc.name_en != ''
    """).fetchall():
        k = row["kod"]
        if k not in kod_lookup:
            kod_lookup[k] = {"name_en": row["name_en"], "method": row["method"] or ""}

    # 3. Update gaps
    gaps = db.execute("""
        SELECT pc.rowid as rid, pa.kod as kod
        FROM parametry_cert pc
        JOIN parametry_analityczne pa ON pa.id = pc.parametr_id
        WHERE (pc.name_en IS NULL OR pc.name_en = '')
    """).fetchall()

    updated = 0
    for row in gaps:
        info = kod_lookup.get(row["kod"])
        if info:
            db.execute("UPDATE parametry_cert SET name_en=?, method=? WHERE rowid=?",
                       (info["name_en"], info["method"], row["rid"]))
            updated += 1

    db.commit()
    db.close()
    print(f"backfill_cert_name_en: {updated} rows updated, {len(gaps) - updated} unfillable")
    return updated

if __name__ == "__main__":
    db_path = None
    for arg in sys.argv[1:]:
        if arg.startswith("--db"):
            db_path = Path(arg.split("=")[1]) if "=" in arg else Path(sys.argv[sys.argv.index(arg) + 1])
    backfill(db_path)
