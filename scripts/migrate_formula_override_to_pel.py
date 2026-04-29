"""One-shot migration: parametry_etapy.formula → produkt_etap_limity.formula.

Idempotent. Skips rows where pel.formula already populated (NOT NULL).
Does NOT clear parametry_etapy.formula (legacy column, untouched).

Usage:
    python scripts/migrate_formula_override_to_pel.py [path/to/db.sqlite]

Default DB path: data/batch_db.sqlite
"""

import json
import sqlite3
import sys
from pathlib import Path

# Repo root assumed parent of this script's parent dir
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mbr.parametry.registry import build_parametry_lab

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/batch_db.sqlite"
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")

rows = conn.execute("""
    SELECT pe.parametr_id, pe.produkt, pe.kontekst, pe.formula, pa.kod
    FROM parametry_etapy pe
    JOIN parametry_analityczne pa ON pa.id = pe.parametr_id
    WHERE pe.formula IS NOT NULL AND pe.formula != ''
""").fetchall()

migrated = 0
skipped = 0
products_to_rebuild = set()

for r in rows:
    ea = conn.execute(
        "SELECT id FROM etapy_analityczne WHERE kod = ?", (r["kontekst"],)
    ).fetchone()
    if not ea:
        print(f"WARN: no etap '{r['kontekst']}' for {r['kod']}/{r['produkt']}, skipping")
        skipped += 1
        continue

    pel = conn.execute(
        "SELECT id, formula FROM produkt_etap_limity "
        "WHERE produkt=? AND etap_id=? AND parametr_id=?",
        (r["produkt"], ea["id"], r["parametr_id"]),
    ).fetchone()
    if not pel:
        print(f"WARN: no pel binding for {r['kod']}/{r['produkt']}/{r['kontekst']}, skipping")
        skipped += 1
        continue

    if pel["formula"] is not None:
        print(f"SKIP: pel already has formula='{pel['formula']}' for {r['kod']}/{r['produkt']}")
        skipped += 1
        continue

    conn.execute(
        "UPDATE produkt_etap_limity SET formula = ? WHERE id = ?",
        (r["formula"], pel["id"]),
    )
    print(f"OK: {r['kod']}/{r['produkt']}/{r['kontekst']} → formula='{r['formula']}'")
    products_to_rebuild.add(r["produkt"])
    migrated += 1

# Rebuild mbr_templates.parametry_lab snapshot for affected products
for produkt in products_to_rebuild:
    plab = build_parametry_lab(conn, produkt)
    cur = conn.execute(
        "UPDATE mbr_templates SET parametry_lab=? WHERE produkt=? AND status='active'",
        (json.dumps(plab, ensure_ascii=False), produkt),
    )
    if cur.rowcount == 0:
        print(f"WARN: no active mbr_template for {produkt} — snapshot not rebuilt")
    else:
        print(f"REBUILT: parametry_lab for {produkt} ({cur.rowcount} row)")

conn.commit()
print(f"\nDone. Migrated: {migrated}, skipped: {skipped}, rebuilt snapshots: {len(products_to_rebuild)}")
