"""
migrate_cert_config.py — one-time migration: cert_config.json → DB

Reads mbr/cert_config.json and:
  1. Enriches parametry_analityczne with name_en and method_code (COALESCE — no overwrite).
  2. Creates parametry_analityczne entries with typ='jakosciowy' for qualitative params
     (those without data_field).
  3. Creates parametry_cert bindings (INSERT OR IGNORE — idempotent).
"""

import json
import sqlite3
import argparse
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_DEFAULT_CONFIG = _ROOT / "mbr" / "cert_config.json"
_DEFAULT_DB = _ROOT / "data" / "batch_db_v4.sqlite"


def migrate(db: sqlite3.Connection, config: dict, dry_run: bool = False) -> dict:
    """
    Populate parametry_cert and enrich parametry_analityczne from config dict.

    Returns a summary dict with counts of actions taken.
    """
    summary = {
        "enriched": 0,
        "created_jakosciowy": 0,
        "cert_bindings": 0,
        "skipped_not_found": 0,
    }

    for produkt, prod_data in config.get("products", {}).items():
        params = prod_data.get("parameters", [])

        for index, param in enumerate(params):
            param_id = param.get("id")
            data_field = param.get("data_field")
            name_en = param.get("name_en")
            method = param.get("method")
            requirement = param.get("requirement")
            fmt = param.get("format", "1")
            qualitative_result = param.get("qualitative_result")

            if data_field:
                # Analytical parameter — find existing row by kod = data_field
                row = db.execute(
                    "SELECT id FROM parametry_analityczne WHERE kod = ?",
                    (data_field,),
                ).fetchone()

                if row is None:
                    print(
                        f"  [WARN] parametry_analityczne: kod='{data_field}' not found "
                        f"(product={produkt}, param={param_id}) — skipping"
                    )
                    summary["skipped_not_found"] += 1
                    continue

                parametr_id = row[0] if isinstance(row, tuple) else row["id"]

                # COALESCE-style update: only set if currently NULL
                db.execute(
                    """
                    UPDATE parametry_analityczne
                    SET name_en     = COALESCE(name_en,     ?),
                        method_code = COALESCE(method_code, ?)
                    WHERE id = ?
                    """,
                    (name_en, method, parametr_id),
                )
                summary["enriched"] += 1

            else:
                # Qualitative parameter — create new parametry_analityczne entry
                label = param.get("name_pl") or param_id
                db.execute(
                    """
                    INSERT OR IGNORE INTO parametry_analityczne
                        (kod, label, typ, name_en, method_code)
                    VALUES (?, ?, 'jakosciowy', ?, ?)
                    """,
                    (param_id, label, name_en, method),
                )

                # Fetch the id (either just inserted or pre-existing)
                row = db.execute(
                    "SELECT id FROM parametry_analityczne WHERE kod = ?",
                    (param_id,),
                ).fetchone()
                parametr_id = row[0] if isinstance(row, tuple) else row["id"]
                summary["created_jakosciowy"] += 1

            # Create parametry_cert binding (idempotent)
            db.execute(
                """
                INSERT OR IGNORE INTO parametry_cert
                    (produkt, parametr_id, kolejnosc, requirement, format, qualitative_result)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (produkt, parametr_id, index, requirement, fmt, qualitative_result),
            )
            summary["cert_bindings"] += 1

    if not dry_run:
        db.commit()
    else:
        db.rollback()

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate cert_config.json → parametry_cert table"
    )
    parser.add_argument(
        "--config",
        default=str(_DEFAULT_CONFIG),
        help=f"Path to cert_config.json (default: {_DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--db",
        default=str(_DEFAULT_DB),
        help=f"Path to SQLite database (default: {_DEFAULT_DB})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run migration but do not commit changes",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    db_path = Path(args.db)

    if not config_path.exists():
        raise SystemExit(f"Config not found: {config_path}")
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        print(f"Migrating {config_path} → {db_path}")
        if args.dry_run:
            print("DRY RUN — no changes will be committed")
        summary = migrate(conn, config, dry_run=args.dry_run)
        print("Done.")
        print(f"  Enriched parametry_analityczne rows:   {summary['enriched']}")
        print(f"  Created jakosciowy params:             {summary['created_jakosciowy']}")
        print(f"  parametry_cert bindings created:       {summary['cert_bindings']}")
        print(f"  Analytical params not found (skipped): {summary['skipped_not_found']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
