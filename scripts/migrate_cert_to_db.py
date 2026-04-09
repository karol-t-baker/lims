"""
migrate_cert_to_db.py — migrate cert_config.json → DB tables

Populates:
  - produkty         (metadata: spec_number, cas_number, etc.)
  - cert_variants    (variant definitions with flags, overrides)
  - parametry_cert   (base parameters variant_id=NULL, variant add_parameters variant_id=<id>)

Idempotent: safe to run multiple times.
Supports --dry-run to preview without committing.
"""

import json
import sqlite3
import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG = _ROOT / "mbr" / "cert_config.json"
_DEFAULT_DB = _ROOT / "data" / "batch_db.sqlite"


def _ensure_unique_constraint(db: sqlite3.Connection, dry_run: bool) -> bool:
    """
    The parametry_cert table originally had UNIQUE(produkt, parametr_id).
    Variant add_parameters need UNIQUE(produkt, parametr_id, variant_id).
    Recreate the table if the old constraint is in place.
    Returns True if migration was performed.
    """
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE name='parametry_cert'"
    ).fetchone()
    if not row:
        return False

    ddl = row[0]
    # Already has the 3-column unique? Nothing to do.
    if "variant_id)" in ddl and "UNIQUE" in ddl:
        # Check if it's the 3-col version
        # crude but sufficient: look for the pattern
        pass

    # Check current unique index columns
    idx_info = db.execute("PRAGMA index_info('sqlite_autoindex_parametry_cert_1')").fetchall()
    col_names = [r[2] for r in idx_info]

    if "variant_id" in col_names:
        return False  # already migrated

    print("[schema] Migrating parametry_cert UNIQUE constraint to include variant_id...")
    if dry_run:
        print("[dry-run] Would recreate parametry_cert table with UNIQUE(produkt, parametr_id, variant_id)")
        return True

    db.executescript("""
        CREATE TABLE parametry_cert_new (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            produkt             TEXT NOT NULL,
            parametr_id         INTEGER NOT NULL REFERENCES parametry_analityczne(id),
            kolejnosc           INTEGER DEFAULT 0,
            requirement         TEXT,
            format              TEXT DEFAULT '1',
            qualitative_result  TEXT,
            variant_id          INTEGER REFERENCES cert_variants(id),
            name_pl             TEXT,
            name_en             TEXT,
            method              TEXT,
            UNIQUE(produkt, parametr_id, variant_id)
        );
        INSERT INTO parametry_cert_new
            SELECT id, produkt, parametr_id, kolejnosc, requirement, format,
                   qualitative_result, variant_id, name_pl, name_en, method
            FROM parametry_cert;
        DROP TABLE parametry_cert;
        ALTER TABLE parametry_cert_new RENAME TO parametry_cert;
    """)
    print("[schema] Done — parametry_cert now has UNIQUE(produkt, parametr_id, variant_id)")
    return True


def _build_kod_to_id(db: sqlite3.Connection) -> dict:
    """Build mapping: parametry_analityczne.kod -> id."""
    rows = db.execute("SELECT id, kod FROM parametry_analityczne").fetchall()
    return {r[1]: r[0] for r in rows}


def _build_label_method_index(db: sqlite3.Connection) -> dict:
    """Build fallback index for qualitative params: (label, method_code) -> id."""
    rows = db.execute(
        "SELECT id, label, method_code FROM parametry_analityczne"
    ).fetchall()
    idx = {}
    for r in rows:
        if r[1]:
            idx.setdefault(r[1].lower().strip(), r[0])
        if r[2]:
            idx.setdefault(r[2].lower().strip(), r[0])
    return idx


def _resolve_parametr_id(
    param: dict,
    kod_to_id: dict,
    label_method_idx: dict,
    db: sqlite3.Connection,
) -> int | None:
    """
    Resolve a cert_config parameter to parametry_analityczne.id.

    For data_field params: kod -> id.
    For qualitative (data_field=null): try matching by label or method_code.
    """
    data_field = param.get("data_field")
    if data_field:
        return kod_to_id.get(data_field)

    # Qualitative parameter — try label/method fallback
    name_pl = (param.get("name_pl") or "").lower().strip()
    method = (param.get("method") or "").lower().strip()

    # Try exact label match
    if name_pl in label_method_idx:
        return label_method_idx[name_pl]

    # Try method match
    if method and method in label_method_idx:
        return label_method_idx[method]

    # Try finding by kod matching the param id
    param_id_str = param.get("id", "")
    if param_id_str in kod_to_id:
        return kod_to_id[param_id_str]

    # Try a DB lookup for qualitative params we know about
    known_qualitative = {
        "odour": "zapach",
        "appearance": "wyglad",
        "colour": "barwa_opis",
        "form": "postac",
    }
    mapped_kod = known_qualitative.get(param_id_str)
    if mapped_kod and mapped_kod in kod_to_id:
        return kod_to_id[mapped_kod]

    # Create a new parametry_analityczne entry for qualitative params
    return None


def _ensure_qualitative_param(
    db: sqlite3.Connection,
    param: dict,
    kod_to_id: dict,
    dry_run: bool,
    summary: dict,
) -> int | None:
    """
    For qualitative params not found in DB, create a new parametry_analityczne entry.
    Uses param['id'] as kod.
    """
    param_id_str = param.get("id", "")
    kod = f"cert_qual_{param_id_str}"

    # Check if already created
    if kod in kod_to_id:
        return kod_to_id[kod]

    label = param.get("name_pl", param_id_str)
    name_en = param.get("name_en", "")
    method_code = param.get("method", "")

    if dry_run:
        print(f"  [dry-run] Would CREATE parametry_analityczne: kod={kod}, label={label}")
        summary["qualitative_created"] += 1
        # Return a fake ID for dry run
        return -1

    db.execute(
        """INSERT OR IGNORE INTO parametry_analityczne
           (kod, label, typ, name_en, method_code, aktywny)
           VALUES (?, ?, 'jakosciowy', ?, ?, 1)""",
        (kod, label, name_en, method_code),
    )
    row = db.execute(
        "SELECT id FROM parametry_analityczne WHERE kod = ?", (kod,)
    ).fetchone()
    if row:
        kod_to_id[kod] = row[0]
        summary["qualitative_created"] += 1
        return row[0]
    return None


def migrate(
    db: sqlite3.Connection,
    config: dict,
    dry_run: bool = False,
) -> dict:
    summary = {
        "products_synced": 0,
        "variants_inserted": 0,
        "variants_updated": 0,
        "params_base_inserted": 0,
        "params_base_updated": 0,
        "params_variant_inserted": 0,
        "params_variant_updated": 0,
        "qualitative_created": 0,
        "skipped": [],
    }

    _ensure_unique_constraint(db, dry_run)

    kod_to_id = _build_kod_to_id(db)
    label_method_idx = _build_label_method_index(db)

    products = config.get("products", {})

    for produkt, prod_data in products.items():
        display_name = prod_data.get("display_name", "")
        spec_number = prod_data.get("spec_number", "")
        cas_number = prod_data.get("cas_number", "")
        expiry_months = prod_data.get("expiry_months", 12)
        opinion_pl = prod_data.get("opinion_pl", "")
        opinion_en = prod_data.get("opinion_en", "")

        # --- 1. Sync produkty metadata ---
        existing = db.execute(
            "SELECT id FROM produkty WHERE nazwa = ?", (produkt,)
        ).fetchone()

        if existing:
            if not dry_run:
                db.execute(
                    """UPDATE produkty
                       SET display_name = ?, spec_number = ?, cas_number = ?,
                           expiry_months = ?, opinion_pl = ?, opinion_en = ?
                       WHERE nazwa = ?""",
                    (display_name, spec_number, cas_number, expiry_months,
                     opinion_pl, opinion_en, produkt),
                )
            print(f"  [produkty] UPDATE {produkt}")
        else:
            if not dry_run:
                db.execute(
                    """INSERT INTO produkty
                       (nazwa, display_name, spec_number, cas_number, expiry_months,
                        opinion_pl, opinion_en, aktywny)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                    (produkt, display_name, spec_number, cas_number,
                     expiry_months, opinion_pl, opinion_en),
                )
            print(f"  [produkty] INSERT {produkt}")
        summary["products_synced"] += 1

        # --- 2. Build param_id -> parametr_analityczne.id map for this product ---
        # Also build config_id -> data_field for remove_parameters resolution
        params = prod_data.get("parameters", [])
        config_id_to_data_field = {}
        for p in params:
            config_id_to_data_field[p["id"]] = p.get("data_field")

        # --- 3. Insert/update base parameters (variant_id = NULL) ---
        for idx, param in enumerate(params):
            pa_id = _resolve_parametr_id(param, kod_to_id, label_method_idx, db)
            if pa_id is None:
                pa_id = _ensure_qualitative_param(db, param, kod_to_id, dry_run, summary)
            if pa_id is None:
                msg = f"{produkt}/{param.get('id')} (qualitative, no match)"
                summary["skipped"].append(msg)
                print(f"  [SKIP] {msg}")
                continue

            requirement = param.get("requirement", "")
            fmt = param.get("format", "1")
            qualitative_result = param.get("qualitative_result")
            name_pl = param.get("name_pl", "")
            name_en = param.get("name_en", "")
            method = param.get("method", "")

            if dry_run:
                print(f"  [dry-run] parametry_cert base: {produkt} param_id={pa_id} "
                      f"({param.get('id')}) kolejnosc={idx}")
                summary["params_base_inserted"] += 1
                continue

            # Upsert: try insert, on conflict update
            existing_pc = db.execute(
                """SELECT id FROM parametry_cert
                   WHERE produkt = ? AND parametr_id = ? AND variant_id IS NULL""",
                (produkt, pa_id),
            ).fetchone()

            if existing_pc:
                db.execute(
                    """UPDATE parametry_cert
                       SET kolejnosc = ?, requirement = ?, format = ?,
                           qualitative_result = ?, name_pl = ?, name_en = ?, method = ?
                       WHERE id = ?""",
                    (idx, requirement, fmt, qualitative_result,
                     name_pl, name_en, method, existing_pc[0]),
                )
                summary["params_base_updated"] += 1
            else:
                db.execute(
                    """INSERT INTO parametry_cert
                       (produkt, parametr_id, kolejnosc, requirement, format,
                        qualitative_result, variant_id, name_pl, name_en, method)
                       VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)""",
                    (produkt, pa_id, idx, requirement, fmt,
                     qualitative_result, name_pl, name_en, method),
                )
                summary["params_base_inserted"] += 1

        # --- 4. Insert/update cert_variants ---
        variants = prod_data.get("variants", [])
        for v_idx, variant in enumerate(variants):
            vid = variant["id"]
            label = variant.get("label", "")
            flags = json.dumps(variant.get("flags", []))
            overrides = variant.get("overrides", {})
            v_spec = overrides.get("spec_number")
            v_opinion_pl = overrides.get("opinion_pl")
            v_opinion_en = overrides.get("opinion_en")
            v_avon_code = overrides.get("avon_code")
            v_avon_name = overrides.get("avon_name")
            remove_params_raw = overrides.get("remove_parameters", [])

            # Resolve remove_parameters: config param IDs -> parametr_analityczne IDs
            remove_param_ids = []
            for rp in remove_params_raw:
                df = config_id_to_data_field.get(rp)
                if df and df in kod_to_id:
                    remove_param_ids.append(kod_to_id[df])
                else:
                    # Might be a qualitative param
                    qual_kod = f"cert_qual_{rp}"
                    if qual_kod in kod_to_id:
                        remove_param_ids.append(kod_to_id[qual_kod])
                    else:
                        msg = f"{produkt}/{vid}: cannot resolve remove_param '{rp}'"
                        summary["skipped"].append(msg)
                        print(f"  [WARN] {msg}")

            remove_params_json = json.dumps(remove_param_ids)

            if dry_run:
                print(f"  [dry-run] cert_variant: {produkt}/{vid} label={label} "
                      f"flags={flags} remove={remove_params_json}")
                summary["variants_inserted"] += 1
            else:
                existing_v = db.execute(
                    "SELECT id FROM cert_variants WHERE produkt = ? AND variant_id = ?",
                    (produkt, vid),
                ).fetchone()

                if existing_v:
                    db.execute(
                        """UPDATE cert_variants
                           SET label = ?, flags = ?, spec_number = ?,
                               opinion_pl = ?, opinion_en = ?,
                               avon_code = ?, avon_name = ?,
                               remove_params = ?, kolejnosc = ?
                           WHERE id = ?""",
                        (label, flags, v_spec, v_opinion_pl, v_opinion_en,
                         v_avon_code, v_avon_name, remove_params_json,
                         v_idx, existing_v[0]),
                    )
                    summary["variants_updated"] += 1
                    cv_id = existing_v[0]
                else:
                    cur = db.execute(
                        """INSERT INTO cert_variants
                           (produkt, variant_id, label, flags, spec_number,
                            opinion_pl, opinion_en, avon_code, avon_name,
                            remove_params, kolejnosc)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (produkt, vid, label, flags, v_spec,
                         v_opinion_pl, v_opinion_en, v_avon_code, v_avon_name,
                         remove_params_json, v_idx),
                    )
                    summary["variants_inserted"] += 1
                    cv_id = cur.lastrowid

            # --- 5. Variant add_parameters ---
            add_params = overrides.get("add_parameters", [])
            for ap_idx, ap in enumerate(add_params):
                ap_pa_id = _resolve_parametr_id(ap, kod_to_id, label_method_idx, db)
                if ap_pa_id is None:
                    ap_pa_id = _ensure_qualitative_param(db, ap, kod_to_id, dry_run, summary)
                if ap_pa_id is None:
                    msg = f"{produkt}/{vid}/add_param/{ap.get('id')} (no match)"
                    summary["skipped"].append(msg)
                    print(f"  [SKIP] {msg}")
                    continue

                ap_req = ap.get("requirement", "")
                ap_fmt = ap.get("format", "1")
                ap_qr = ap.get("qualitative_result")
                ap_name_pl = ap.get("name_pl", "")
                ap_name_en = ap.get("name_en", "")
                ap_method = ap.get("method", "")

                if dry_run:
                    print(f"  [dry-run] parametry_cert add_param: {produkt}/{vid} "
                          f"param_id={ap_pa_id} ({ap.get('id')})")
                    summary["params_variant_inserted"] += 1
                    continue

                # Base params count + ap_idx for ordering
                base_count = len(params)
                ap_kolejnosc = base_count + ap_idx

                existing_apc = db.execute(
                    """SELECT id FROM parametry_cert
                       WHERE produkt = ? AND parametr_id = ? AND variant_id = ?""",
                    (produkt, ap_pa_id, cv_id),
                ).fetchone()

                if existing_apc:
                    db.execute(
                        """UPDATE parametry_cert
                           SET kolejnosc = ?, requirement = ?, format = ?,
                               qualitative_result = ?, name_pl = ?, name_en = ?, method = ?
                           WHERE id = ?""",
                        (ap_kolejnosc, ap_req, ap_fmt, ap_qr,
                         ap_name_pl, ap_name_en, ap_method, existing_apc[0]),
                    )
                    summary["params_variant_updated"] += 1
                else:
                    db.execute(
                        """INSERT INTO parametry_cert
                           (produkt, parametr_id, kolejnosc, requirement, format,
                            qualitative_result, variant_id, name_pl, name_en, method)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (produkt, ap_pa_id, ap_kolejnosc, ap_req, ap_fmt,
                         ap_qr, cv_id, ap_name_pl, ap_name_en, ap_method),
                    )
                    summary["params_variant_inserted"] += 1

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Migrate cert_config.json → DB (produkty, cert_variants, parametry_cert)"
    )
    parser.add_argument(
        "--config", type=Path, default=_DEFAULT_CONFIG,
        help=f"Path to cert_config.json (default: {_DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--db", type=Path, default=_DEFAULT_DB,
        help=f"Path to SQLite DB (default: {_DEFAULT_DB})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview changes without committing to DB",
    )
    args = parser.parse_args()

    if not args.config.exists():
        print(f"ERROR: Config not found: {args.config}", file=sys.stderr)
        sys.exit(1)
    if not args.db.exists():
        print(f"ERROR: DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    with open(args.config) as f:
        config = json.load(f)

    db = sqlite3.connect(str(args.db))
    db.execute("PRAGMA foreign_keys = ON")

    try:
        summary = migrate(db, config, dry_run=args.dry_run)

        if args.dry_run:
            print("\n=== DRY RUN — no changes committed ===")
            db.rollback()
        else:
            db.commit()
            print("\n=== Changes committed ===")

        print(f"\nStats:")
        print(f"  Products synced:          {summary['products_synced']}")
        print(f"  Variants inserted:        {summary['variants_inserted']}")
        print(f"  Variants updated:         {summary['variants_updated']}")
        print(f"  Base params inserted:     {summary['params_base_inserted']}")
        print(f"  Base params updated:      {summary['params_base_updated']}")
        print(f"  Variant params inserted:  {summary['params_variant_inserted']}")
        print(f"  Variant params updated:   {summary['params_variant_updated']}")
        print(f"  Qualitative created:      {summary['qualitative_created']}")
        if summary["skipped"]:
            print(f"  Skipped ({len(summary['skipped'])}):")
            for s in summary["skipped"]:
                print(f"    - {s}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
