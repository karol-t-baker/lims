#!/usr/bin/env python3
"""One-shot server deployment: cert SSOT migration + platkowanie setup.

Run on the production server after deploying new code:
    cd /path/to/project && python3 scripts/deploy_cert_ssot.py

What it does:
1. Runs init_mbr_tables() — creates cert_variants table + new parametry_cert columns
2. Runs migrate_cert_to_db.py — populates cert_variants + parametry_cert from cert_config.json
3. Marks platkowanie products in produkty.typy
4. Adds Alkinol substraty (Alkohole 30/70, Chemal EO 20)
5. Regenerates cert_config.json export from DB

Safe to run multiple times (idempotent).
"""
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "batch_db.sqlite"


def main():
    print("=== 1. Schema migrations ===")
    from mbr.db import db_session
    from mbr.models import init_mbr_tables
    with db_session() as db:
        init_mbr_tables(db)
    print("  OK — cert_variants table + parametry_cert columns ready")

    print("\n=== 2. Migrate cert_config.json → DB ===")
    from scripts.migrate_cert_to_db import migrate
    config_path = PROJECT_ROOT / "mbr" / "cert_config.json"
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    db_conn = sqlite3.connect(str(DB_PATH))
    db_conn.row_factory = sqlite3.Row
    migrate(db_conn, config)
    db_conn.close()

    print("\n=== 3. Mark platkowanie products ===")
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    PLATKOWANIE_PRODUCTS = [
        "Alkinol", "Alkinol_B", "HSH_CS_3070", "Chemal_CS_3070", "Monamid_KO"
    ]
    updated = 0
    for prod in PLATKOWANIE_PRODUCTS:
        row = db.execute("SELECT id, typy FROM produkty WHERE nazwa=?", (prod,)).fetchone()
        if not row:
            print(f"  SKIP {prod} — not in produkty table")
            continue
        typy = json.loads(row["typy"] or '["szarza"]')
        if "platkowanie" not in typy:
            typy.append("platkowanie")
            db.execute("UPDATE produkty SET typy=? WHERE id=?", (json.dumps(typy), row["id"]))
            updated += 1
            print(f"  + {prod} → typy={typy}")
        else:
            print(f"  OK {prod} — already has platkowanie")
    db.commit()
    print(f"  {updated} products updated")

    print("\n=== 4. Add substraty for Alkinole ===")
    SUBSTRATY = [
        {"nazwa": "Alkohole 30/70", "produkty": ["Alkinol", "Alkinol_B"]},
        {"nazwa": "Chemal EO 20", "produkty": ["Alkinol", "Alkinol_B"]},
    ]
    added = 0
    for sub in SUBSTRATY:
        db.execute("INSERT OR IGNORE INTO substraty (nazwa) VALUES (?)", (sub["nazwa"],))
        sub_id = db.execute("SELECT id FROM substraty WHERE nazwa=?", (sub["nazwa"],)).fetchone()["id"]
        for prod in sub["produkty"]:
            existing = db.execute(
                "SELECT id FROM substrat_produkty WHERE substrat_id=? AND produkt=?",
                (sub_id, prod)
            ).fetchone()
            if not existing:
                db.execute(
                    "INSERT INTO substrat_produkty (substrat_id, produkt) VALUES (?, ?)",
                    (sub_id, prod)
                )
                added += 1
                print(f"  + {sub['nazwa']} → {prod}")
            else:
                print(f"  OK {sub['nazwa']} → {prod} — already linked")
    db.commit()
    print(f"  {added} links added")

    db.close()

    print("\n=== 5. Regenerate cert_config.json ===")
    from mbr.certs.generator import save_cert_config_export
    with db_session() as db:
        save_cert_config_export(db)
    print("  OK — cert_config.json regenerated")

    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
