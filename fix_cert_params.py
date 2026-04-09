"""
Fix missing certificate parameters in parametry_cert table.

Reads the extraction report from Word templates, compares with existing
parametry_cert bindings, and inserts missing entries + fixes ordering.
"""

import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("data/batch_db.sqlite")
REPORT_PATH = Path("data/cert_extraction_report.json")

# Map from report matched_kod to actual parametry_analityczne.kod
KOD_MAP = {
    "odour": "cert_qual_odour",
    "appearance": "cert_qual_appearance",
    "form": "cert_qual_form",
    "active_matter": "sa",
    "dry_matter": "sm",
    "ph": "ph_10proc",
    "density": "gestosc",
    "free_amine": "wolna_amina",
    "free_aminoamide": "wolna_amina",
    "alkalinity": "alkalicznosc",
    "barwa_jod": "barwa_fau",
    "barwa_gardner": "barwa_fau",
    "colour": "barwa_opis",
    "c16": "cert_qual_c16",
    "c18": "cert_qual_c18",
    "dea": "dietanolamina",
    "dietanolamide": "dietanolamina",
}

# New parametry_analityczne entries to create if not present
NEW_PA_ENTRIES = {
    "glicerol": {
        "kod": "glicerol",
        "label": "Glicerol [%]",
        "typ": "analiza",
        "name_en": "Glycerol [%]",
        "method_code": "L911",
        "precision": 2,
    },
    "cert_qual_c14": {
        "kod": "cert_qual_c14",
        "label": "%C14:0",
        "typ": "cert_qual",
        "name_en": "%C14:0",
        "method_code": "metoda dostawcy surowca/according to supplier's CoA",
        "precision": 1,
    },
    "rozklad_kwasow": {
        "kod": "rozklad_kwasow",
        "label": "Rozkład kwasów tłuszczowych [%]",
        "typ": "cert_qual",
        "name_en": "Fatty acid distribution [%]",
        "method_code": "metoda dostawcy surowca/according to supplier's CoA",
        "precision": 1,
    },
}

# Special handling for report entries with matched_kod=None
# Maps (product, param_index) -> db_kod to use
NONE_KOD_OVERRIDES = {
    # Chelamid_DK [4] Glicerol -> new 'glicerol' entry
    ("Chelamid_DK", 4): "glicerol",
    # Chemal_CS_3070 [2] and Chemal_CS_5050 [2] Liczba zmydlenia -> already 'lz' in DB
    ("Chemal_CS_3070", 2): "lz",
    ("Chemal_CS_5050", 2): "lz",
    # Glikoster_P [7] %C14:0 -> new 'cert_qual_c14' entry
    ("Glikoster_P", 7): "cert_qual_c14",
    # Kwas_Stearynowy [2] Liczba jodowa -> already 'li' in DB
    ("Kwas_Stearynowy", 2): "li",
    # Monamid_KO [7] Rozkład kwasów tłuszczowych -> new entry
    ("Monamid_KO", 7): "rozklad_kwasow",
}


def ensure_pa_entries(cur: sqlite3.Cursor) -> dict:
    """Create any missing parametry_analityczne entries. Returns kod->id map."""
    cur.execute("SELECT id, kod FROM parametry_analityczne")
    pa_map = {r["kod"]: r["id"] for r in cur.fetchall()}

    for kod, entry in NEW_PA_ENTRIES.items():
        if kod not in pa_map:
            cur.execute(
                """INSERT INTO parametry_analityczne (kod, label, typ, name_en, method_code, precision, aktywny)
                   VALUES (?, ?, ?, ?, ?, ?, 1)""",
                (entry["kod"], entry["label"], entry["typ"], entry["name_en"],
                 entry["method_code"], entry["precision"]),
            )
            pa_map[kod] = cur.lastrowid
            print(f"  Created parametry_analityczne: {kod} (id={pa_map[kod]})")

    return pa_map


def resolve_db_kod(report_kod, product, param_idx):
    """Resolve a report matched_kod to actual DB kod."""
    if report_kod is None:
        override = NONE_KOD_OVERRIDES.get((product, param_idx))
        if override:
            return override
        return None
    return KOD_MAP.get(report_kod, report_kod)


def deduplicate_params(params, product):
    """
    Deduplicate report params for a product.
    Some products have variant-specific duplicates in the report.
    Keep only the first occurrence of each db_kod.
    """
    seen = set()
    result = []
    for idx, param in enumerate(params):
        db_kod = resolve_db_kod(param["matched_kod"], product, idx)
        if db_kod is None:
            print(f"  WARNING: Skipping {product}[{idx}] '{param['name_pl']}' - no kod mapping")
            continue
        if db_kod not in seen:
            seen.add(db_kod)
            result.append((param, db_kod))
    return result


def infer_format(param):
    """Infer format field from requirement/qualitative_result."""
    req = param.get("requirement") or ""
    qual = param.get("qualitative_result")

    # Qualitative params (appearance, odour, form) -> format '1'
    if qual and ("zgodny" in qual.lower() or "right" in qual.lower()):
        return "1"

    # Check if requirement has decimal precision hints
    # e.g., "max 2,00" -> 2 decimal places
    import re
    match = re.search(r"\d+[,.](\d+)", req)
    if match:
        decimals = len(match.group(1))
        return str(decimals)

    # Ranges like "135-160" or "29,0-33,0"
    match = re.search(r"(\d+[,.]?\d*)\s*[-–÷]\s*(\d+[,.]?\d*)", req)
    if match:
        for val in [match.group(1), match.group(2)]:
            if "," in val or "." in val:
                parts = val.replace(".", ",").split(",")
                if len(parts) == 2:
                    return str(len(parts[1]))
        return "0"

    return "1"


def main():
    with open(REPORT_PATH) as f:
        report = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()

    # Ensure new parametry_analityczne entries exist
    pa_map = ensure_pa_entries(cur)

    stats = {"inserted": 0, "reordered": 0, "skipped": 0}

    for product, data in sorted(report["products"].items()):
        params = data["parameters"]
        unique_params = deduplicate_params(params, product)

        # Get existing DB entries
        cur.execute(
            """SELECT pa.kod, pc.id, pc.kolejnosc, pc.parametr_id
               FROM parametry_cert pc
               JOIN parametry_analityczne pa ON pc.parametr_id = pa.id
               WHERE pc.produkt = ? AND pc.variant_id IS NULL
               ORDER BY pc.kolejnosc""",
            (product,),
        )
        existing = {}
        for r in cur.fetchall():
            existing[r["kod"]] = {
                "id": r["id"],
                "kolejnosc": r["kolejnosc"],
                "parametr_id": r["parametr_id"],
            }

        changes_for_product = []

        for target_order, (param, db_kod) in enumerate(unique_params):
            pa_id = pa_map.get(db_kod)
            if pa_id is None:
                print(f"  ERROR: {product} - kod '{db_kod}' not in parametry_analityczne!")
                stats["skipped"] += 1
                continue

            if db_kod in existing:
                # Already exists - check ordering
                entry = existing[db_kod]
                if entry["kolejnosc"] != target_order:
                    cur.execute(
                        "UPDATE parametry_cert SET kolejnosc = ? WHERE id = ?",
                        (target_order, entry["id"]),
                    )
                    changes_for_product.append(
                        f"  REORDER: {db_kod} {entry['kolejnosc']} -> {target_order}"
                    )
                    stats["reordered"] += 1
            else:
                # Missing - insert
                name_pl = param["name_pl"].replace("\n", " ").strip()
                name_en = (param.get("name_en") or "").replace("\n", " ").strip()
                requirement = (param.get("requirement") or "").replace("\n", " ").strip()
                method = (param.get("method") or "").replace("\n", " ").strip()
                qual = param.get("qualitative_result")
                if qual:
                    qual = qual.replace("\n", " ").strip()

                # Try to get format from existing DB entries for same kod in other products
                cur.execute(
                    "SELECT format FROM parametry_cert WHERE parametr_id = ? AND variant_id IS NULL LIMIT 1",
                    (pa_id,),
                )
                fmt_row = cur.fetchone()
                fmt = fmt_row["format"] if fmt_row else infer_format(param)

                cur.execute(
                    """INSERT INTO parametry_cert
                       (produkt, parametr_id, kolejnosc, requirement, format,
                        qualitative_result, variant_id, name_pl, name_en, method)
                       VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)""",
                    (product, pa_id, target_order, requirement, fmt,
                     qual, name_pl, name_en, method),
                )
                changes_for_product.append(
                    f"  INSERT [{target_order}]: {db_kod} -> '{name_pl}'"
                )
                stats["inserted"] += 1

        if changes_for_product:
            print(f"\n{product}:")
            for c in changes_for_product:
                print(c)

    conn.commit()
    conn.close()

    print(f"\n{'='*60}")
    print(f"Summary: {stats['inserted']} inserted, {stats['reordered']} reordered, {stats['skipped']} skipped")

    # Regenerate cert_config.json export
    print("\nRegenerating cert_config.json...")
    sys.path.insert(0, ".")
    from mbr.db import db_session
    from mbr.certs.generator import save_cert_config_export
    with db_session() as db:
        save_cert_config_export(db)
    print("Done! cert_config.json updated.")


if __name__ == "__main__":
    main()
