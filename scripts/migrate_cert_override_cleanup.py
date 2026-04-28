"""Migration: NULL out parametry_cert.name_pl/name_en/method overrides that equal
the registry value (parametry_analityczne.label/name_en/method_code) after whitespace
normalization.

After this migration, cert UI semantics: empty override = inherit from registry.
Idempotent — safe to re-run.

Usage:
    python -m scripts.migrate_cert_override_cleanup            # run on default DB
    python -m scripts.migrate_cert_override_cleanup --dry-run  # report only
    python -m scripts.migrate_cert_override_cleanup --db /path/to/db.sqlite

Logs detailed report to stdout: how many rows nulled per field, which products kept
explicit overrides.
"""

import argparse
import re
import sqlite3
import sys
from pathlib import Path

_WS_RE = re.compile(r"\s+")


def _norm(s):
    """Whitespace normalize: strip + collapse internal runs to single space.
    Case-sensitive (case has meaning in this domain — e.g. 'PN-EN' vs 'pn-en')."""
    if s is None:
        return None
    return _WS_RE.sub(" ", s.strip())


def _eq_norm(a, b):
    return _norm(a) == _norm(b)


def run_migration(db, dry_run=False):
    """Walk parametry_cert; for each row, NULL the override fields that match the
    registry value (after whitespace normalization).

    Args:
        db: sqlite3.Connection (caller commits unless dry_run).
        dry_run: if True, count what would change but don't UPDATE.

    Returns:
        Stats dict: {rows_processed, nulled_total, preserved_total,
                     nulled_per_field: {name_pl, name_en, method},
                     preserved_examples: [{produkt, kod, field, override_value, registry_value}]}
    """
    rows = db.execute(
        """
        SELECT pc.rowid AS rid, pc.produkt, pc.variant_id, pc.parametr_id,
               pc.name_pl, pc.name_en, pc.method,
               pa.kod, pa.label, pa.name_en AS pa_name_en, pa.method_code
        FROM parametry_cert pc
        JOIN parametry_analityczne pa ON pa.id = pc.parametr_id
        """
    ).fetchall()

    nulled = {"name_pl": 0, "name_en": 0, "method": 0}
    preserved_examples = []
    nulled_total = 0
    preserved_total = 0

    for r in rows:
        updates = {}
        for cert_field, registry_val in [
            ("name_pl", r["label"]),
            ("name_en", r["pa_name_en"]),
            ("method", r["method_code"]),
        ]:
            override = r[cert_field]
            if override is None:
                continue
            if _eq_norm(override, registry_val):
                updates[cert_field] = None
                nulled[cert_field] += 1
                nulled_total += 1
            else:
                preserved_total += 1
                if len(preserved_examples) < 50:
                    preserved_examples.append({
                        "produkt": r["produkt"],
                        "variant_id": r["variant_id"],
                        "kod": r["kod"],
                        "field": cert_field,
                        "override_value": override,
                        "registry_value": registry_val,
                    })

        if updates and not dry_run:
            sets = ", ".join(f"{k}=NULL" for k in updates)
            db.execute(f"UPDATE parametry_cert SET {sets} WHERE rowid=?", (r["rid"],))

    if not dry_run:
        db.commit()

    return {
        "rows_processed": len(rows),
        "nulled_total": nulled_total,
        "preserved_total": preserved_total,
        "nulled_per_field": nulled,
        "preserved_examples": preserved_examples,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/batch_db.sqlite", help="Path to SQLite DB")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    stats = run_migration(conn, dry_run=args.dry_run)

    print("=" * 60)
    print(f"Cert override cleanup — {'DRY RUN' if args.dry_run else 'EXECUTED'}")
    print("=" * 60)
    print(f"Rows processed:           {stats['rows_processed']}")
    print(f"Override fields nulled:   {stats['nulled_total']}")
    print(f"  - name_pl:  {stats['nulled_per_field']['name_pl']}")
    print(f"  - name_en:  {stats['nulled_per_field']['name_en']}")
    print(f"  - method:   {stats['nulled_per_field']['method']}")
    print(f"Real overrides preserved: {stats['preserved_total']}")
    if stats['preserved_examples']:
        print()
        print("Sample preserved overrides (first 50):")
        for ex in stats['preserved_examples']:
            v = " (variant)" if ex.get("variant_id") else ""
            print(f"  {ex['produkt']}{v}/{ex['kod']}/{ex['field']}: ")
            print(f"    override:  {ex['override_value']!r}")
            print(f"    registry:  {ex['registry_value']!r}")
    conn.close()


if __name__ == "__main__":
    main()
