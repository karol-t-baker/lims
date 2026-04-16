"""Migrate parameter binding data from parametry_etapy + etap_parametry into the
extended produkt_etap_limity table, and cert metadata into parametry_cert.

Does NOT drop the legacy tables — that happens in a later PR after application
code is refactored to read from the new SSOT.

Usage:
    python -m scripts.migrate_parametry_ssot [--db PATH] [--dry-run] [--verify-only] [--force]
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


MIGRATION_NAME = "parametry_ssot_v1"


def backup(db_path: str) -> str:
    """Copy DB file next to original with timestamped suffix. Return backup path."""
    src = Path(db_path)
    if not src.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")
    dst = src.with_suffix(src.suffix + f".bak-pre-parametry-ssot")
    shutil.copy2(src, dst)
    return str(dst)


def already_applied(db: sqlite3.Connection) -> bool:
    """Check if migration has run before using _migrations marker table."""
    db.execute(
        "CREATE TABLE IF NOT EXISTS _migrations ("
        " name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    row = db.execute(
        "SELECT 1 FROM _migrations WHERE name=?", (MIGRATION_NAME,)
    ).fetchone()
    return row is not None


def mark_applied(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO _migrations (name, applied_at) VALUES (?, ?)",
        (MIGRATION_NAME, datetime.now().isoformat(timespec="seconds")),
    )


def preflight(db: sqlite3.Connection) -> list[str]:
    """Return list of blocker messages. Empty list = OK to proceed."""
    blockers: list[str] = []

    null_rows = db.execute(
        "SELECT COUNT(*) AS n FROM parametry_etapy WHERE produkt IS NULL"
    ).fetchone()["n"]
    if null_rows > 0:
        blockers.append(
            f"{null_rows} parametry_etapy rows with NULL produkt (shared) — "
            "resolve manually (assign to product or delete) before migrating."
        )

    return blockers


# Columns to add to produkt_etap_limity. ALTER TABLE ADD COLUMN can't add CHECK
# inline in SQLite, but values are controlled by application + init_mbr_tables
# CREATE TABLE (which does include CHECK) for fresh DBs.
_NEW_COLUMNS = [
    ("kolejnosc",       "INTEGER NOT NULL DEFAULT 0"),
    ("formula",         "TEXT"),
    ("sa_bias",         "REAL"),
    ("krok",            "INTEGER"),
    ("wymagany",        "INTEGER NOT NULL DEFAULT 0"),
    ("grupa",           "TEXT NOT NULL DEFAULT 'lab'"),
    ("dla_szarzy",      "INTEGER NOT NULL DEFAULT 1"),
    ("dla_zbiornika",   "INTEGER NOT NULL DEFAULT 1"),
    ("dla_platkowania", "INTEGER NOT NULL DEFAULT 0"),
]


# Known kontekst → etap kod mappings. cert_variant is not a measurement etap —
# those rows go to parametry_cert instead and are NOT added to produkt_pipeline.
_NON_ETAP_KONTEKSTY = {"cert_variant"}


def _kontekst_to_etap_id(db: sqlite3.Connection, kontekst: str) -> int | None:
    """Resolve kontekst name to etapy_analityczne.id. None if non-etap (cert_variant)."""
    if kontekst in _NON_ETAP_KONTEKSTY:
        return None
    row = db.execute(
        "SELECT id FROM etapy_analityczne WHERE kod=?", (kontekst,)
    ).fetchone()
    return row["id"] if row else None


def ensure_pipeline_for_legacy(db: sqlite3.Connection) -> list[tuple[str, int]]:
    """For each (produkt, kontekst) in parametry_etapy lacking a produkt_pipeline row,
    create one. Returns list of (produkt, etap_id) inserts made."""
    pairs = db.execute(
        "SELECT DISTINCT produkt, kontekst FROM parametry_etapy "
        "WHERE produkt IS NOT NULL"
    ).fetchall()
    inserted: list[tuple[str, int]] = []
    for pair in pairs:
        produkt = pair["produkt"]
        kontekst = pair["kontekst"]
        etap_id = _kontekst_to_etap_id(db, kontekst)
        if etap_id is None:
            continue
        exists = db.execute(
            "SELECT 1 FROM produkt_pipeline WHERE produkt=? AND etap_id=?",
            (produkt, etap_id),
        ).fetchone()
        if exists:
            continue
        next_kol = db.execute(
            "SELECT COALESCE(MAX(kolejnosc), 0) + 1 AS k FROM produkt_pipeline WHERE produkt=?",
            (produkt,),
        ).fetchone()["k"]
        db.execute(
            "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES (?, ?, ?)",
            (produkt, etap_id, next_kol),
        )
        inserted.append((produkt, etap_id))
    return inserted


def alter_schema(db: sqlite3.Connection) -> None:
    """Add new columns to produkt_etap_limity if missing. Idempotent."""
    existing = {r["name"] for r in db.execute(
        "PRAGMA table_info(produkt_etap_limity)"
    ).fetchall()}
    for name, decl in _NEW_COLUMNS:
        if name not in existing:
            db.execute(f"ALTER TABLE produkt_etap_limity ADD COLUMN {name} {decl}")


def copy_limits(db: sqlite3.Connection) -> int:
    """Copy limits from parametry_etapy into produkt_etap_limity. Returns rows touched.

    - Skips kontekst='cert_variant' (handled by migrate_cert_fields instead)
    - If target row exists and destination value is NOT NULL, keep destination
    - Default typ flags: dla_szarzy=1, dla_zbiornika=1, dla_platkowania=0
    - Assumes ensure_pipeline_for_legacy has already run
    """
    src_rows = db.execute(
        "SELECT parametr_id, kontekst, produkt, min_limit, max_limit, nawazka_g, "
        "       precision, target, kolejnosc, formula, sa_bias, krok, grupa "
        "FROM parametry_etapy WHERE produkt IS NOT NULL"
    ).fetchall()
    touched = 0
    for r in src_rows:
        etap_id = _kontekst_to_etap_id(db, r["kontekst"])
        if etap_id is None:
            continue
        dst = db.execute(
            "SELECT id, min_limit, max_limit, nawazka_g, precision, spec_value, "
            "       kolejnosc, formula, sa_bias, krok, grupa "
            "FROM produkt_etap_limity WHERE produkt=? AND etap_id=? AND parametr_id=?",
            (r["produkt"], etap_id, r["parametr_id"]),
        ).fetchone()
        if dst is None:
            db.execute(
                "INSERT INTO produkt_etap_limity "
                "(produkt, etap_id, parametr_id, min_limit, max_limit, nawazka_g, precision, "
                " spec_value, kolejnosc, formula, sa_bias, krok, grupa, "
                " dla_szarzy, dla_zbiornika, dla_platkowania) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 0)",
                (r["produkt"], etap_id, r["parametr_id"],
                 r["min_limit"], r["max_limit"], r["nawazka_g"], r["precision"],
                 r["target"], r["kolejnosc"] or 0, r["formula"], r["sa_bias"],
                 r["krok"], r["grupa"] or "lab"),
            )
        else:
            # Partial update: fill only NULLs in destination with non-NULL from source
            updates: list[tuple[str, object]] = []
            src_map = {
                "min_limit": r["min_limit"],
                "max_limit": r["max_limit"],
                "nawazka_g": r["nawazka_g"],
                "precision": r["precision"],
                "spec_value": r["target"],
                "kolejnosc": r["kolejnosc"],
                "formula":   r["formula"],
                "sa_bias":   r["sa_bias"],
                "krok":      r["krok"],
                "grupa":     r["grupa"],
            }
            for col, src_val in src_map.items():
                if src_val is not None and dst[col] is None:
                    updates.append((col, src_val))
            if updates:
                sets = ", ".join(f"{c}=?" for c, _ in updates)
                vals = [v for _, v in updates] + [dst["id"]]
                db.execute(f"UPDATE produkt_etap_limity SET {sets} WHERE id=?", vals)
        touched += 1
    return touched


def migrate_sa_bias(db: sqlite3.Connection) -> int:
    """Copy non-null sa_bias from etap_parametry to every matching produkt_etap_limity
    row, ONLY where the destination sa_bias is NULL. Returns updates made."""
    src_rows = db.execute(
        "SELECT etap_id, parametr_id, sa_bias FROM etap_parametry WHERE sa_bias IS NOT NULL"
    ).fetchall()
    updated = 0
    for r in src_rows:
        cur = db.execute(
            "UPDATE produkt_etap_limity SET sa_bias=? "
            "WHERE etap_id=? AND parametr_id=? AND sa_bias IS NULL",
            (r["sa_bias"], r["etap_id"], r["parametr_id"]),
        )
        updated += cur.rowcount
    return updated


def migrate_cert_fields(db: sqlite3.Connection) -> int:
    """Copy on_cert=1 rows from parametry_etapy into parametry_cert.
    UPSERT by (produkt, parametr_id, variant_id)."""
    src_rows = db.execute(
        "SELECT parametr_id, produkt, cert_requirement, cert_format, "
        "       cert_qualitative_result, cert_kolejnosc, cert_variant_id "
        "FROM parametry_etapy "
        "WHERE on_cert=1 AND produkt IS NOT NULL"
    ).fetchall()
    touched = 0
    for r in src_rows:
        existing = db.execute(
            "SELECT id FROM parametry_cert "
            "WHERE produkt=? AND parametr_id=? "
            "  AND ((variant_id IS NULL AND ? IS NULL) OR variant_id = ?)",
            (r["produkt"], r["parametr_id"], r["cert_variant_id"], r["cert_variant_id"]),
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE parametry_cert SET "
                " requirement         = COALESCE(?, requirement), "
                " format              = COALESCE(?, format), "
                " qualitative_result  = COALESCE(?, qualitative_result), "
                " kolejnosc           = COALESCE(?, kolejnosc) "
                "WHERE id=?",
                (r["cert_requirement"], r["cert_format"],
                 r["cert_qualitative_result"], r["cert_kolejnosc"], existing["id"]),
            )
        else:
            db.execute(
                "INSERT INTO parametry_cert "
                "(produkt, parametr_id, variant_id, requirement, format, "
                " qualitative_result, kolejnosc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (r["produkt"], r["parametr_id"], r["cert_variant_id"],
                 r["cert_requirement"], r["cert_format"],
                 r["cert_qualitative_result"], r["cert_kolejnosc"]),
            )
        touched += 1
    return touched


def postflight(db: sqlite3.Connection) -> list[str]:
    """Return list of post-migration validation errors. Empty list = OK."""
    errors: list[str] = []

    # Check 1: every active MBR template has at least one visible binding
    rows = db.execute("""
        SELECT mt.produkt
        FROM mbr_templates mt
        WHERE mt.status = 'active'
          AND NOT EXISTS (
            SELECT 1 FROM produkt_etap_limity pel
             WHERE pel.produkt = mt.produkt
               AND (pel.dla_szarzy=1 OR pel.dla_zbiornika=1 OR pel.dla_platkowania=1)
          )
    """).fetchall()
    for r in rows:
        errors.append(f"Active product '{r['produkt']}' has no visible bindings in produkt_etap_limity.")

    # Check 2: no orphan bindings (etap_id not in that produkt's pipeline)
    rows = db.execute("""
        SELECT pel.produkt, pel.etap_id
        FROM produkt_etap_limity pel
        WHERE NOT EXISTS (
            SELECT 1 FROM produkt_pipeline pp
             WHERE pp.produkt = pel.produkt AND pp.etap_id = pel.etap_id
        )
    """).fetchall()
    for r in rows:
        errors.append(
            f"Orphan binding: produkt='{r['produkt']}' etap_id={r['etap_id']} "
            "has no matching produkt_pipeline row."
        )

    return errors


def migrate(db: sqlite3.Connection, dry_run: bool = False) -> None:
    """Run the full migration inside a single transaction."""
    if already_applied(db):
        print(f"Migration {MIGRATION_NAME} already applied — skipping.")
        return

    blockers = preflight(db)
    if blockers:
        print("Pre-flight checks failed:", file=sys.stderr)
        for b in blockers:
            print(f"  - {b}", file=sys.stderr)
        raise SystemExit(1)

    if dry_run:
        print("Dry run — no changes will be committed.")

    alter_schema(db)
    created_pipelines = ensure_pipeline_for_legacy(db)
    if created_pipelines:
        print(f"Created {len(created_pipelines)} produkt_pipeline entries for legacy products:")
        for produkt, etap_id in created_pipelines:
            print(f"  - {produkt} → etap_id={etap_id}")

    n_limits = copy_limits(db)
    print(f"Copied/verified {n_limits} limit bindings.")

    n_sa = migrate_sa_bias(db)
    if n_sa:
        print(f"Propagated sa_bias to {n_sa} produkt_etap_limity rows.")

    n_cert = migrate_cert_fields(db)
    print(f"Migrated {n_cert} cert metadata rows to parametry_cert.")

    errors = postflight(db)
    if errors:
        print("Post-flight validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        raise SystemExit(2)

    if dry_run:
        db.rollback()
        print("Dry run complete — rolled back.")
    else:
        mark_applied(db)
        db.commit()
        print(f"Migration {MIGRATION_NAME} committed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/batch_db.sqlite")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run migration inside a transaction and roll back at the end.")
    parser.add_argument("--verify-only", action="store_true",
                        help="Run postflight only without altering data.")
    parser.add_argument("--force", action="store_true",
                        help="Re-run even if _migrations marker is present.")
    args = parser.parse_args()

    if not args.dry_run and not args.verify_only:
        bkp = backup(args.db)
        print(f"Backup: {bkp}")

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")

    try:
        if args.verify_only:
            errors = postflight(db)
            if errors:
                for e in errors:
                    print(f"  - {e}")
                raise SystemExit(2)
            print("Verification OK.")
        else:
            if args.force:
                db.execute("DELETE FROM _migrations WHERE name=?", (MIGRATION_NAME,))
            migrate(db, dry_run=args.dry_run)
    finally:
        db.close()


if __name__ == "__main__":
    main()
