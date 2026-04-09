"""One-time migration: cert_config.json product metadata → produkty table.

Usage:
    python scripts/migrate_produkty.py [--dry-run]
"""
import json
import sys
from pathlib import Path


def migrate(db, config: dict, dry_run: bool = False) -> dict:
    products = config.get("products", {})
    stats = {"updated": 0, "created": 0}
    for prod_key, prod_cfg in products.items():
        display_name = prod_cfg.get("display_name", "")
        spec_number = prod_cfg.get("spec_number", "")
        cas_number = prod_cfg.get("cas_number", "")
        expiry_months = prod_cfg.get("expiry_months", 12)
        opinion_pl = prod_cfg.get("opinion_pl", "")
        opinion_en = prod_cfg.get("opinion_en", "")

        row = db.execute("SELECT id FROM produkty WHERE nazwa = ?", (prod_key,)).fetchone()
        if row:
            db.execute("""
                UPDATE produkty SET
                    display_name  = COALESCE(NULLIF(display_name, ''), ?),
                    spec_number   = COALESCE(NULLIF(spec_number, ''), ?),
                    cas_number    = COALESCE(NULLIF(cas_number, ''), ?),
                    expiry_months = CASE WHEN expiry_months IS NULL OR expiry_months = 12 THEN ? ELSE expiry_months END,
                    opinion_pl    = COALESCE(NULLIF(opinion_pl, ''), ?),
                    opinion_en    = COALESCE(NULLIF(opinion_en, ''), ?)
                WHERE nazwa = ?
            """, (display_name, spec_number, cas_number, expiry_months,
                  opinion_pl, opinion_en, prod_key))
            stats["updated"] += 1
        else:
            db.execute("""
                INSERT INTO produkty (nazwa, display_name, spec_number, cas_number,
                    expiry_months, opinion_pl, opinion_en)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (prod_key, display_name, spec_number, cas_number,
                  expiry_months, opinion_pl, opinion_en))
            stats["created"] += 1
    if not dry_run:
        db.commit()
    else:
        db.rollback()
    return stats


def main():
    dry_run = "--dry-run" in sys.argv
    project_root = Path(__file__).resolve().parent.parent
    config_path = project_root / "mbr" / "cert_config.json"
    db_path = project_root / "data" / "batch_db_v4.sqlite"
    if not config_path.exists():
        print(f"ERROR: {config_path} not found"); sys.exit(1)
    if not db_path.exists():
        print(f"ERROR: {db_path} not found"); sys.exit(1)
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    print(f"Migrating {len(config.get('products', {}))} products...")
    if dry_run:
        print("(DRY RUN)")
    stats = migrate(conn, config, dry_run=dry_run)
    print(f"Done: {stats['updated']} updated, {stats['created']} created")
    conn.close()


if __name__ == "__main__":
    main()
