#!/usr/bin/env python3
"""
Apply cert extraction report to update:
1. parametry_analityczne table in batch_db.sqlite (name_en, method_code)
2. cert_config.json (name_pl, name_en, requirement, method, qualitative_result)

Usage:
    python apply_cert_extraction.py [--dry-run]
"""

import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
REPORT_PATH = BASE_DIR / "data" / "cert_extraction_report.json"
CERT_CONFIG_PATH = BASE_DIR / "mbr" / "cert_config.json"
DB_PATH = BASE_DIR / "data" / "batch_db.sqlite"

DRY_RUN = "--dry-run" in sys.argv


def load_data():
    with open(REPORT_PATH, encoding="utf-8") as f:
        report = json.load(f)
    with open(CERT_CONFIG_PATH, encoding="utf-8") as f:
        cert_config = json.load(f)
    return report, cert_config


def extract_l_method(method_str):
    """Extract L### method code from a method string."""
    if not method_str:
        return None
    m = re.search(r'\bL\d{3,4}\b', method_str)
    return m.group(0) if m else None


def is_garbled(text):
    """Detect obviously garbled/truncated text from bad Word parsing."""
    if not text:
        return True
    text = text.strip()
    # Too short to be a real name
    if len(text) < 3:
        return True
    # Starts with lowercase and looks like a fragment (e.g., "mol)")
    if text[0].islower() and len(text) < 15:
        return True
    # Contains unbalanced brackets
    if text.count('(') != text.count(')') or text.count('[') != text.count(']'):
        return True
    return False


def name_quality_score(text):
    """Score a name for quality — higher is better."""
    if not text:
        return 0
    score = len(text)
    # Penalize newlines in names
    score -= text.count('\n') * 5
    # Penalize garbled text
    if is_garbled(text):
        score -= 50
    # Bonus for having proper units in brackets
    if re.search(r'\[.*\]', text):
        score += 10
    return score


def deduplicate_params(parameters):
    """For params with same matched_kod, keep the one with better data."""
    seen = {}
    for p in parameters:
        kod = p.get("matched_kod")
        if not kod:
            continue
        if kod not in seen:
            seen[kod] = p
        else:
            existing = seen[kod]
            # Score based on name_pl quality
            existing_score = name_quality_score(existing.get("name_pl", ""))
            new_score = name_quality_score(p.get("name_pl", ""))
            if new_score > existing_score:
                seen[kod] = p
    return seen


def update_db(report, conn):
    """Update parametry_analityczne: fill in name_en and method_code where NULL/empty."""
    cursor = conn.cursor()
    cursor.execute("SELECT kod, label, name_en, method_code FROM parametry_analityczne")
    db_rows = {row[0]: {"label": row[1], "name_en": row[2], "method_code": row[3]}
               for row in cursor.fetchall()}

    # Collect ALL name_en and method_code candidates from report, pick best
    name_en_candidates = {}   # kod -> list of name_en strings
    method_candidates = {}    # kod -> list of L### codes

    for product_name, product_data in report["products"].items():
        for param in product_data["parameters"]:
            kod = param.get("matched_kod")
            if not kod:
                continue

            name_en = (param.get("name_en") or "").strip().replace("\n", " ")
            if name_en and not is_garbled(name_en):
                name_en_candidates.setdefault(kod, []).append(name_en)

            method = param.get("method") or ""
            l_code = extract_l_method(method)
            if l_code:
                method_candidates.setdefault(kod, []).append(l_code)

    # Pick best name_en: longest non-garbled one
    best_name_en = {}
    for kod, names in name_en_candidates.items():
        best = max(names, key=lambda n: name_quality_score(n))
        if not is_garbled(best):
            best_name_en[kod] = best

    # Pick best method: most common (they should all be the same)
    best_method_code = {}
    for kod, methods in method_candidates.items():
        from collections import Counter
        best_method_code[kod] = Counter(methods).most_common(1)[0][0]

    updated_name_en = 0
    updated_method_code = 0

    for kod, db_info in sorted(db_rows.items()):
        new_name_en = None
        new_method = None

        if not db_info["name_en"] and kod in best_name_en:
            new_name_en = best_name_en[kod]

        if not db_info["method_code"] and kod in best_method_code:
            new_method = best_method_code[kod]

        if not new_name_en and not new_method:
            continue

        parts = []
        if new_name_en:
            parts.append(f"name_en='{new_name_en}'")
        if new_method:
            parts.append(f"method_code='{new_method}'")
        print(f"  DB UPDATE {kod}: {', '.join(parts)}")

        if not DRY_RUN:
            if new_name_en and new_method:
                cursor.execute(
                    "UPDATE parametry_analityczne SET name_en = ?, method_code = ? WHERE kod = ?",
                    (new_name_en, new_method, kod),
                )
            elif new_name_en:
                cursor.execute(
                    "UPDATE parametry_analityczne SET name_en = ? WHERE kod = ?",
                    (new_name_en, kod),
                )
            else:
                cursor.execute(
                    "UPDATE parametry_analityczne SET method_code = ? WHERE kod = ?",
                    (new_method, kod),
                )

        if new_name_en:
            updated_name_en += 1
        if new_method:
            updated_method_code += 1

    if not DRY_RUN:
        conn.commit()

    return updated_name_en, updated_method_code


def clean_text(text):
    """Normalize text: collapse multiple spaces around newlines, strip."""
    if not text:
        return text
    return re.sub(r'\s*\n\s*', '\n', text).strip()


def is_regression(field, old_val, new_val):
    """Check if updating old_val -> new_val would be a regression."""
    if not old_val:
        return False  # always ok to fill in empty

    # Don't replace degree sign with space or nothing
    if '°' in old_val and '°' not in new_val:
        return True

    # Don't introduce double spaces
    if '  ' not in old_val and '  ' in new_val:
        return True

    # Don't drop units in brackets (e.g., "[%]" disappearing)
    old_units = re.findall(r'\[.*?\]', old_val)
    new_units = re.findall(r'\[.*?\]', new_val)
    if old_units and not new_units:
        return True

    # Don't replace properly spaced units with no-space variants
    # e.g., "[mg KOH/g]" -> "[mgKOH/g]" is a typo in the Word template
    if field in ('name_pl', 'name_en'):
        # Compare without newlines for a fair check
        old_flat = old_val.replace('\n', ' ')
        new_flat = new_val.replace('\n', ' ')
        # If removing all spaces from both yields the same, but old has proper spaces, keep old
        if (old_flat.replace(' ', '') == new_flat.replace(' ', '')
                and old_flat.count(' ') > new_flat.count(' ')):
            return True

    # Don't replace a name with a shorter garbled version
    if field in ('name_pl', 'name_en'):
        if is_garbled(new_val):
            return True
        # Don't shorten names significantly (more than losing half the length)
        if len(new_val) < len(old_val) * 0.6:
            return True

    return False


def update_cert_config(report, cert_config, conn):
    """Update cert_config.json parameters to match Word template values."""
    cursor = conn.cursor()
    cursor.execute("SELECT kod, precision FROM parametry_analityczne")
    db_precision = {row[0]: row[1] for row in cursor.fetchall()}

    updated_params = 0
    added_params = 0
    discrepancies = []

    for product_name, product_data in report["products"].items():
        if product_name not in cert_config["products"]:
            discrepancies.append(f"Product '{product_name}' in report but not in cert_config")
            continue

        config_product = cert_config["products"][product_name]
        config_params = config_product.get("parameters", [])

        # Build lookup: id -> index, data_field -> index
        config_by_id = {}
        config_by_data_field = {}
        for i, cp in enumerate(config_params):
            config_by_id[cp.get("id")] = i
            if cp.get("data_field"):
                config_by_data_field[cp["data_field"]] = i

        # Deduplicate report params by matched_kod
        deduped = deduplicate_params(product_data["parameters"])

        for kod, rp in deduped.items():
            # Find matching config param by id or data_field
            idx = None
            if kod in config_by_id:
                idx = config_by_id[kod]
            elif kod in config_by_data_field:
                idx = config_by_data_field[kod]

            if idx is None:
                if rp.get("in_cert_config"):
                    # Report says it's in config but we can't find it —
                    # likely a variant-only param or uses different id mapping
                    discrepancies.append(
                        f"{product_name}: param kod='{kod}' marked in_cert_config "
                        f"but not found in base params (may be variant-only)"
                    )
                else:
                    # Genuinely new parameter — add it
                    new_param = {
                        "id": kod,
                        "name_pl": clean_text(rp.get("name_pl", "")),
                        "name_en": clean_text(rp.get("name_en", "")),
                        "requirement": clean_text(rp.get("requirement", "")),
                        "method": clean_text(rp.get("method", "")),
                        "data_field": kod,
                    }
                    if kod in db_precision and db_precision[kod] is not None:
                        new_param["format"] = str(db_precision[kod])

                    qr = rp.get("qualitative_result")
                    if qr:
                        new_param["qualitative_result"] = clean_text(qr)
                        if not extract_l_method(rp.get("method", "")):
                            new_param["data_field"] = None

                    config_params.append(new_param)
                    added_params += 1
                    print(f"  ADD {product_name}: {kod} ({rp.get('name_pl', '')})")
                continue

            cp = config_params[idx]
            changes = []

            report_name_pl = clean_text(rp.get("name_pl", ""))
            report_name_en = clean_text(rp.get("name_en", ""))
            report_requirement = clean_text(rp.get("requirement", ""))
            report_method = clean_text(rp.get("method", ""))
            report_qr = clean_text(rp.get("qualitative_result"))

            # Update name_pl
            if report_name_pl and report_name_pl != cp.get("name_pl", ""):
                if not is_regression("name_pl", cp.get("name_pl", ""), report_name_pl):
                    changes.append(f"name_pl: '{cp.get('name_pl', '')}' -> '{report_name_pl}'")
                    cp["name_pl"] = report_name_pl

            # Update name_en
            if report_name_en and report_name_en != cp.get("name_en", ""):
                if not is_regression("name_en", cp.get("name_en", ""), report_name_en):
                    changes.append(f"name_en: '{cp.get('name_en', '')}' -> '{report_name_en}'")
                    cp["name_en"] = report_name_en

            # Update requirement
            if report_requirement and report_requirement != cp.get("requirement", ""):
                changes.append(f"requirement: '{cp.get('requirement', '')}' -> '{report_requirement}'")
                cp["requirement"] = report_requirement

            # Update method
            if report_method and report_method != cp.get("method", ""):
                changes.append(f"method: '{cp.get('method', '')}' -> '{report_method}'")
                cp["method"] = report_method

            # Update qualitative_result
            if report_qr is not None and report_qr:
                current_qr = cp.get("qualitative_result")
                if report_qr != current_qr:
                    changes.append(f"qualitative_result: '{current_qr}' -> '{report_qr}'")
                    cp["qualitative_result"] = report_qr

            if changes:
                updated_params += 1
                print(f"  UPDATE {product_name}/{cp.get('id', kod)}: {'; '.join(changes)}")

        config_product["parameters"] = config_params

    return updated_params, added_params, discrepancies


def main():
    print(f"{'[DRY RUN] ' if DRY_RUN else ''}Applying cert extraction report...")
    print()

    report, cert_config = load_data()
    print(f"Loaded report: {len(report['products'])} products")
    print(f"Loaded cert_config: {len(cert_config['products'])} products")
    print()

    # Backups
    if not DRY_RUN:
        backup_config = CERT_CONFIG_PATH.with_suffix(".json.bak")
        shutil.copy2(CERT_CONFIG_PATH, backup_config)
        print(f"Backup: {backup_config}")

        backup_db = DB_PATH.with_suffix(".sqlite.bak")
        shutil.copy2(DB_PATH, backup_db)
        print(f"Backup: {backup_db}")
        print()

    conn = sqlite3.connect(str(DB_PATH))

    # Step 2: Update DB
    print("=== Step 2: Update parametry_analityczne ===")
    name_en_count, method_count = update_db(report, conn)
    print()

    # Step 3: Update cert_config.json
    print("=== Step 3: Update cert_config.json ===")
    updated_params, added_params, discrepancies = update_cert_config(report, cert_config, conn)
    print()

    # Save cert_config
    if not DRY_RUN:
        with open(CERT_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cert_config, f, indent=2, ensure_ascii=False)
        print(f"Saved {CERT_CONFIG_PATH}")
    print()

    conn.close()

    # Summary
    print("=== Summary ===")
    print(f"DB rows updated (name_en): {name_en_count}")
    print(f"DB rows updated (method_code): {method_count}")
    print(f"cert_config parameters updated: {updated_params}")
    print(f"cert_config parameters added: {added_params}")
    print()

    if discrepancies:
        print(f"=== Discrepancies ({len(discrepancies)}) ===")
        for d in discrepancies:
            print(f"  - {d}")
    else:
        print("No discrepancies found.")


if __name__ == "__main__":
    main()
