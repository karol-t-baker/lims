"""
Clear ALL per-product / per-variant cert overrides on parametry_cert:
  - name_pl
  - name_en
  - method
  - format  (precyzja)

After this script runs every cert row falls back to the registry values
(parametry_analityczne.label / .name_en / .method_code / .precision).

Default mode is --dry-run: prints what would change but does NOT touch the DB.
Pass --execute to apply.

Audit: one cert.config.updated event per distinct (produkt, variant_id),
logged with actor_login='system'.

Idempotent — re-running is a no-op when DB is already clean.

Run:
    python -m scripts.archive.clear_cert_all_overrides              # dry-run
    python -m scripts.archive.clear_cert_all_overrides --execute    # apply
    python -m scripts.archive.clear_cert_all_overrides --execute --db /path/to/batch.sqlite
"""
import argparse
import os
import sqlite3
import sys

# scripts/archive/ → repo root is two levels up
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

FIELDS = ("name_pl", "name_en", "method", "format")


def clear_all(db: sqlite3.Connection, dry_run: bool = True) -> dict:
    """Clear all 4 override fields on parametry_cert.

    Returns stats dict: {rows_with_any_override, per_field_cleared, scopes}.
    """
    rows = db.execute(
        f"""SELECT id, produkt, variant_id, {", ".join(FIELDS)}
              FROM parametry_cert
             WHERE {" OR ".join(f"{f} IS NOT NULL" for f in FIELDS)}"""
    ).fetchall()

    per_field = {f: sum(1 for r in rows if r[f] is not None) for f in FIELDS}
    scopes = sorted({(r["produkt"], r["variant_id"]) for r in rows},
                    key=lambda t: (t[0], t[1] or 0))

    if not rows:
        return {"rows": 0, "per_field": per_field, "scopes": []}

    if not dry_run:
        db.execute(
            f"""UPDATE parametry_cert
                   SET {", ".join(f"{f} = NULL" for f in FIELDS)}
                 WHERE {" OR ".join(f"{f} IS NOT NULL" for f in FIELDS)}"""
        )

        # Audit per scope
        from mbr.shared import audit
        for produkt, variant_id in scopes:
            scope_rows = [r for r in rows
                          if r["produkt"] == produkt and r["variant_id"] == variant_id]
            audit.log_event(
                audit.EVENT_CERT_CONFIG_UPDATED,
                entity_type="cert",
                entity_label=produkt if variant_id is None else f"{produkt}#variant={variant_id}",
                payload={
                    "produkt": produkt,
                    "variant_id": variant_id,
                    "action": "all_overrides_cleared",
                    "rows_cleared": len(scope_rows),
                    "name_pl_cleared": sum(1 for r in scope_rows if r["name_pl"] is not None),
                    "name_en_cleared": sum(1 for r in scope_rows if r["name_en"] is not None),
                    "method_cleared":  sum(1 for r in scope_rows if r["method"]  is not None),
                    "format_cleared":  sum(1 for r in scope_rows if r["format"]  is not None),
                    "reason": "bulk reset — registry becomes SSOT for all 4 fields",
                },
                actors=audit.actors_system(),
                db=db,
            )
        db.commit()

    return {"rows": len(rows), "per_field": per_field, "scopes": scopes}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/batch_db.sqlite", help="Path to SQLite DB")
    ap.add_argument("--execute", action="store_true",
                    help="Apply changes (default: dry-run, prints stats only)")
    args = ap.parse_args()

    db_path = args.db
    if not os.path.exists(db_path):
        print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    stats = clear_all(conn, dry_run=not args.execute)
    conn.close()

    mode = "EXECUTED" if args.execute else "DRY-RUN (no changes)"
    print("=" * 60)
    print(f"clear_cert_all_overrides — {mode}")
    print("=" * 60)
    print(f"DB:                       {db_path}")
    print(f"Rows with any override:   {stats['rows']}")
    for f in FIELDS:
        print(f"  - {f:9s} cleared:  {stats['per_field'][f]}")
    print(f"Affected scopes:          {len(stats['scopes'])} (produkt × variant)")

    if not args.execute and stats["rows"]:
        print()
        print("Re-run with --execute to apply.")

    if args.execute and stats["rows"]:
        # Re-export cert_config.json — overrides resolved against registry
        from mbr.certs.generator import save_cert_config_export
        save_cert_config_export()
        print()
        print("Re-exported mbr/cert_config.json from DB.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
