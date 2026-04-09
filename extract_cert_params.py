#!/usr/bin/env python3
"""
Extract certificate parameters from Word templates (.docx) in data/wzory/
and produce a JSON report comparing with existing cert_config.json.
"""

import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from docx import Document

BASE_DIR = Path(__file__).resolve().parent
WZORY_DIR = BASE_DIR / "data" / "wzory"
CERT_CONFIG_PATH = BASE_DIR / "mbr" / "cert_config.json"
OUTPUT_PATH = BASE_DIR / "data" / "cert_extraction_report.json"


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

# Known variant keywords (order matters — longer first for greedy match)
VARIANT_KEYWORDS = [
    "ADAM&PARTNER", "ADAM&PARTNERS",
    "NUMER ZAMÓWIENIA",
    "NR_ZAM", "nr zamówienia", "nr zamowienia", "nr zam",
    "nr. zamówienia", "nr zam.",
    "PEŁNA NR ZAM", "PEŁNA",
    "LEHVOSS", "OQEMA", "SKINCHEM", "PRIME", "REVADA",
    "AVON", "GHP", "Elin",
    "Loreal Belgia", "Loreal Włochy", "Loreal",
    "Kosmepol",
    "GLOBAL_DR. MIELE", "DR. MIELE",
    "REUSE",
    "HQ",
    "MB",
    "bez kodu",
    "z nr zamówienia",
]


def normalise_product_name(raw: str) -> str:
    """Normalise product name to match cert_config keys (spaces → _)."""
    return raw.strip().replace(" ", "_")


def parse_filename(fname: str):
    """
    Extract (product_name, variant_hint) from a certificate template filename.
    Returns (product_display_name, variant_label).
    """
    # Normalise to NFC — macOS uses NFD in filenames (e.g. Ś = S + combining accent)
    name = unicodedata.normalize('NFC', fname)
    # Strip extension
    name = re.sub(r'\.(docx?|DOCX?)$', '', name)

    # Remove leading client-variant prefixes
    leading_variant = None
    for prefix in ["AVON ", "PRIME ", "LEHVOSS ", "REVADA "]:
        if name.upper().startswith(prefix.upper()):
            leading_variant = prefix.strip()
            name = name[len(prefix):]
            break

    # Remove the entire "Świadectwo / Certificate" prefix block in one regex.
    # Matches any combination of "Świadectwo" and "Certificate" separated by
    # arbitrary punctuation/whitespace, in any order.
    # Examples handled:
    #   "Świadectwo_Certificate-", "ŚwiadectwoCertificate-",
    #   "Świadectwo - Certificate -", "Certificate Świadectwo-",
    #   "Świadectwo_Certificate_", "Świadectwo_Certificate "
    CERT_WORD = r'(?:[ŚśS]wiadectwo|Certificate)'
    SEP = r'[\s_\-/]*'
    # Match 1 or 2 cert-words with separators between and after
    name = re.sub(
        rf'^{SEP}{CERT_WORD}{SEP}(?:{CERT_WORD}{SEP})?',
        '', name, flags=re.IGNORECASE
    )
    name = re.sub(r'^[\s_\-/]+', '', name)

    # Now split on WZÓR (case insensitive) — everything before is product+variant,
    # everything after is additional variant hints.
    # WZÓR can be preceded by space, underscore, or dash (e.g. "-WZÓR", "_WZÓR", " WZÓR")
    # Also handle "wzór_bez kodu" and "WZÓR_PEŁNA" where underscore follows WZÓR
    # \b won't work before _ so use a lookahead for non-alpha instead
    parts = re.split(r'[\s_\-]+[Ww][Zz][OoÓó][Rr](?=[\s_\-]|$)[\s_]*', name, maxsplit=1)
    before_wzor = parts[0].strip()
    after_wzor = parts[1].strip() if len(parts) > 1 else ""

    # Collect variant keywords from both halves
    variants_found = []
    if leading_variant:
        variants_found.append(leading_variant.upper())

    # Check after_wzor for variant keywords (longest-first to avoid sub-matches)
    after_lower = after_wzor.lower() if after_wzor else ""
    for kw in VARIANT_KEYWORDS:
        if after_lower and kw.lower() in after_lower:
            kw_up = kw.upper()
            # Skip if a longer already-matched variant contains this one
            already_covered = any(
                kw_up != v and kw_up in v for v in variants_found
            )
            if not already_covered and kw_up not in variants_found:
                variants_found.append(kw_up)
                # Remove any shorter variants that this one covers
                variants_found = [
                    v for v in variants_found
                    if v == kw_up or v not in kw_up
                ]

    # Strip variant keywords from the end of before_wzor to isolate product name
    remaining = before_wzor.rstrip(" -")
    changed = True
    while changed:
        changed = False
        for kw in VARIANT_KEYWORDS:
            pattern = re.compile(r'[\s\-]+' + re.escape(kw) + r'\s*$', re.IGNORECASE)
            m = pattern.search(remaining)
            if m:
                if kw.upper() not in [v.upper() for v in variants_found]:
                    variants_found.append(kw.upper())
                remaining = remaining[:m.start()].rstrip(" -")
                changed = True
                break

    product_display = remaining.strip().rstrip(" -")
    # Clean up extra whitespace
    product_display = re.sub(r'\s+', ' ', product_display).strip()

    # Normalise known product name variations to match cert_config keys
    # Strip trailing dashes/dots from product name (e.g. "Cheminox K-" → "Cheminox K")
    product_display = product_display.rstrip(" -.")

    PRODUCT_ALIASES = {
        "Chegina K40 GL": "Chegina K40GL",
        "Chegina K40 GLO": "Chegina K40GLO",
        "Kw. Stearynowy": "Kwas Stearynowy",
        "Chemal CS 30 70": "Chemal CS 3070",
        "Chemal CS 50 50": "Chemal CS 5050",
        "HSH CS 30 70": "HSH CS 3070",
        "Chegina GLOL40": "Chegina GLOL40",
        "Alstermid": "Alstermid K",
        "Chegina": "Chegina KK",
        "Cheminox K": "Cheminox K",
        "Cheminox K 35": "Cheminox K35",
        "Chegina CC": "Chegina CC",
        "Chegina CCR": "Chegina CCR",
    }
    for alias, canonical in PRODUCT_ALIASES.items():
        if product_display == alias:
            product_display = canonical
            break

    # Determine variant label
    if not variants_found:
        variant = "base"
    else:
        variant = " ".join(sorted(set(v for v in variants_found)))

    return product_display, variant


# ---------------------------------------------------------------------------
# Name splitting (PL / EN)
# ---------------------------------------------------------------------------

# Patterns that indicate a PL/EN split point (but NOT units like g/cm3, mgKOH/g)
UNIT_SLASH_PATTERNS = [
    r'g/cm[23]', r'mg\s*KOH/g', r'mg KOH/g', r'g\s*I2?/100\s*g',
    r'g\s*J2?/100\s*g', r'%', r'°C', r'\uf0b0C', r'0C',
]


def split_pl_en(raw_name: str):
    """
    Split a parameter name into (name_pl, name_en).
    Handles patterns like:
      "Nazwa PL\\n/Name EN"
      "Nazwa PL/Name EN"  (but not unit slashes)
      "Nazwa PL\\nName EN"
    """
    raw = raw_name.strip()

    # Pattern 1: newline followed by slash — clearest separator
    if '\n/' in raw:
        parts = raw.split('\n/', 1)
        return parts[0].strip(), parts[1].strip()

    # Pattern 2: slash followed by newline (e.g. "Barwa w skali Hazena/\nColour")
    if '/\n' in raw:
        parts = raw.split('/\n', 1)
        return parts[0].strip(), parts[1].strip()

    # Pattern 3: newline without slash
    if '\n' in raw:
        parts = raw.split('\n', 1)
        pl = parts[0].strip()
        en = parts[1].strip()
        # Remove leading slash if present
        if en.startswith('/'):
            en = en[1:].strip()
        return pl, en

    # Pattern 4: slash — but only if it looks like a language split, not a unit
    # Heuristic: if there's a slash and the text after it starts with a capital letter
    # and it's not part of a known unit pattern
    slash_positions = [m.start() for m in re.finditer(r'/', raw)]
    for pos in slash_positions:
        before = raw[:pos].strip()
        after = raw[pos+1:].strip()

        # Skip if this slash is part of a unit
        is_unit = False
        for up in UNIT_SLASH_PATTERNS:
            # Check if the slash at this position is inside a unit pattern
            for m in re.finditer(up, raw):
                if m.start() <= pos <= m.end():
                    is_unit = True
                    break
            if is_unit:
                break

        if is_unit:
            continue

        # Check if after part looks like English (starts with capital, contains latin chars)
        if after and after[0].isupper() and re.match(r'^[A-Z]', after):
            return before, after

        # Also match "/ Name" pattern with space
        if after and len(after) > 1:
            # Check if it could be an English name
            if re.match(r'^[A-Za-z]', after):
                return before, after

    return raw, ""


# ---------------------------------------------------------------------------
# Parameter matching
# ---------------------------------------------------------------------------

def build_method_name_index(cert_config: dict):
    """
    Build lookup structures from existing cert_config for matching.
    Returns dict: (method, normalised_name_pl) → param info
    """
    all_params = {}  # id → param dict with product list
    method_index = defaultdict(list)  # method → list of param dicts

    for prod_key, prod_data in cert_config.get("products", {}).items():
        # Collect base parameters + variant override add_parameters
        all_product_params = list(prod_data.get("parameters", []))
        for v in prod_data.get("variants", []):
            for op in v.get("overrides", {}).get("add_parameters", []):
                all_product_params.append(op)

        for p in all_product_params:
            pid = p.get("id", "")
            method = p.get("method", "").strip()
            name_pl = p.get("name_pl", "").strip()

            entry = {
                "id": pid,
                "name_pl": name_pl,
                "name_en": p.get("name_en", ""),
                "method": method,
                "data_field": p.get("data_field"),
                "product": prod_key,
            }
            if method:
                method_index[method].append(entry)
            if pid not in all_params:
                all_params[pid] = entry

    return all_params, method_index


def normalise_for_match(s: str) -> str:
    """Normalise a string for fuzzy matching."""
    s = s.lower().strip()
    s = re.sub(r'[\s\-_]+', ' ', s)
    s = s.replace('ó', 'o').replace('ł', 'l').replace('ś', 's')
    s = s.replace('ą', 'a').replace('ę', 'e').replace('ć', 'c')
    s = s.replace('ń', 'n').replace('ż', 'z').replace('ź', 'z')
    s = s.replace('\uf0b0', '°')
    return s


def match_parameter(name_pl: str, method: str, method_index: dict, all_params: dict):
    """
    Try to match an extracted parameter to an existing one in cert_config.
    Returns (matched_id, in_cert_config) or (None, False).
    """
    norm_name = normalise_for_match(name_pl)

    # Direct method match
    if method in method_index:
        candidates = method_index[method]
        # Try exact name match first
        for c in candidates:
            if normalise_for_match(c["name_pl"]) == norm_name:
                return c["id"], True

        # Try partial name match (name contains or is contained)
        for c in candidates:
            cn = normalise_for_match(c["name_pl"])
            # Extract the "core" name without units
            core_extracted = re.sub(r'\[.*?\]', '', norm_name).strip()
            core_config = re.sub(r'\[.*?\]', '', cn).strip()
            if core_extracted == core_config:
                return c["id"], True
            if core_extracted in core_config or core_config in core_extracted:
                return c["id"], True

        # If method matched but name didn't exactly match, still return first
        # (same method usually = same parameter type)
        if len(candidates) == 1:
            return candidates[0]["id"], True
        # Multiple candidates — pick best overlap
        best = None
        best_score = 0
        for c in candidates:
            cn = normalise_for_match(c["name_pl"])
            # Simple word overlap score
            words_e = set(norm_name.split())
            words_c = set(cn.split())
            overlap = len(words_e & words_c)
            if overlap > best_score:
                best_score = overlap
                best = c
        if best:
            return best["id"], True

    # Try matching by name alone across all params
    for pid, p in all_params.items():
        cn = normalise_for_match(p["name_pl"])
        if cn == norm_name:
            return pid, True

    # Special known mappings for qualitative params
    qual_map = {
        "zapach": "odour",
        "wyglad": "appearance",
    }
    simple = normalise_for_match(name_pl).split()[0] if name_pl else ""
    if simple in qual_map:
        return qual_map[simple], True

    return None, False


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def extract_from_docx(filepath: Path):
    """
    Extract parameter rows from a .docx certificate template.
    Returns list of dicts with name_pl, name_en, requirement, method, qualitative_result.
    """
    doc = Document(str(filepath))
    params = []

    for table in doc.tables:
        if len(table.columns) < 4:
            continue

        # Check if first row looks like a header
        header_cells = [cell.text.strip().lower() for cell in table.rows[0].cells]
        is_param_table = any("parametr" in h or "inspection" in h for h in header_cells)

        if not is_param_table:
            continue

        for row_idx, row in enumerate(table.rows):
            if row_idx == 0:  # Skip header
                continue

            cells = [cell.text.strip() for cell in row.cells]
            if len(cells) < 4:
                continue

            raw_name = cells[0]
            requirement = cells[1]
            method = cells[2]
            result = cells[3]

            if not raw_name:
                continue

            name_pl, name_en = split_pl_en(raw_name)
            qualitative_result = result if result else None

            params.append({
                "name_pl": name_pl,
                "name_en": name_en,
                "requirement": requirement,
                "method": method,
                "qualitative_result": qualitative_result,
            })

    return params


def main():
    # Load existing cert_config
    with open(CERT_CONFIG_PATH) as f:
        cert_config = json.load(f)

    all_params, method_index = build_method_name_index(cert_config)

    # Process all files
    files_parsed = 0
    files_skipped = 0
    skip_reasons = []

    # product_display → { "variants_found": set, "parameters": list }
    products = defaultdict(lambda: {"variants_found": set(), "parameters": []})
    # Track unique params globally: (name_pl_normalised, method) → param info
    global_params = {}

    for fname in sorted(os.listdir(str(WZORY_DIR))):
        fpath = os.path.join(str(WZORY_DIR), fname)

        if not fname.lower().endswith(('.docx', '.doc')):
            continue

        if fname.lower().endswith('.doc') and not fname.lower().endswith('.docx'):
            # Old format, likely to fail
            try:
                params = extract_from_docx(fpath)
            except Exception as e:
                files_skipped += 1
                skip_reasons.append(f"{fname}: {e}")
                print(f"  SKIP (old .doc): {fname}")
                continue

        try:
            params = extract_from_docx(fpath)
        except Exception as e:
            files_skipped += 1
            skip_reasons.append(f"{fname}: {e}")
            print(f"  SKIP: {fname} — {e}")
            continue

        if not params:
            files_skipped += 1
            skip_reasons.append(f"{fname}: no parameter table found")
            print(f"  SKIP (no table): {fname}")
            continue

        product_display, variant = parse_filename(fname)
        product_key = normalise_product_name(product_display)

        files_parsed += 1
        print(f"  OK: {fname} → {product_key} [{variant}] ({len(params)} params)")

        products[product_key]["variants_found"].add(variant)

        # Add params (dedup by name_pl + method within product)
        existing_keys = {(p["name_pl"], p["method"]) for p in products[product_key]["parameters"]}
        for p in params:
            key = (p["name_pl"], p["method"])
            if key not in existing_keys:
                products[product_key]["parameters"].append(p)
                existing_keys.add(key)

            # Global tracking
            gkey = (normalise_for_match(p["name_pl"]), p["method"])
            if gkey not in global_params:
                global_params[gkey] = {**p, "products": [product_key]}
            elif product_key not in global_params[gkey]["products"]:
                global_params[gkey]["products"].append(product_key)

    # Match parameters to cert_config
    unmatched_params = []
    matched_count = 0

    for prod_key, prod_data in products.items():
        for p in prod_data["parameters"]:
            matched_id, in_config = match_parameter(
                p["name_pl"], p["method"], method_index, all_params
            )
            p["matched_kod"] = matched_id
            p["in_cert_config"] = in_config
            if in_config:
                matched_count += 1
            else:
                gkey = (normalise_for_match(p["name_pl"]), p["method"])
                gp = global_params.get(gkey, {})
                unmatched_params.append({
                    "name_pl": p["name_pl"],
                    "name_en": p.get("name_en", ""),
                    "method": p["method"],
                    "requirement": p["requirement"],
                    "products": gp.get("products", [prod_key]),
                })

    # Deduplicate unmatched
    seen_unmatched = set()
    deduped_unmatched = []
    for u in unmatched_params:
        key = (u["name_pl"], u["method"])
        if key not in seen_unmatched:
            seen_unmatched.add(key)
            deduped_unmatched.append(u)

    # Find params missing English names in cert_config
    missing_en = []
    for pid, pinfo in all_params.items():
        if not pinfo.get("name_en"):
            # Try to find English name from extracted data
            suggested = ""
            for gkey, gp in global_params.items():
                if gp.get("matched_kod") == pid or (
                    normalise_for_match(gp["name_pl"]) == normalise_for_match(pinfo["name_pl"])
                ):
                    if gp.get("name_en"):
                        suggested = gp["name_en"]
                        break
            missing_en.append({
                "kod": pid,
                "current_label": pinfo["name_pl"],
                "suggested_en": suggested,
            })

    # Count unique params
    unique_params_set = set()
    for prod_data in products.values():
        for p in prod_data["parameters"]:
            unique_params_set.add((normalise_for_match(p["name_pl"]), p["method"]))

    # Build output
    output = {
        "products": {},
        "unmatched_params": deduped_unmatched,
        "missing_name_en": missing_en,
        "stats": {
            "files_parsed": files_parsed,
            "files_skipped": files_skipped,
            "unique_products": len(products),
            "unique_parameters": len(unique_params_set),
            "matched_to_db": matched_count,
            "unmatched": len(deduped_unmatched),
            "skip_reasons": skip_reasons,
        }
    }

    for prod_key in sorted(products.keys()):
        pd = products[prod_key]
        output["products"][prod_key] = {
            "variants_found": sorted(pd["variants_found"]),
            "parameters": pd["parameters"],
        }

    # Write report
    os.makedirs(OUTPUT_PATH.parent, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Print summary
    print("\n" + "=" * 70)
    print("CERTIFICATE TEMPLATE EXTRACTION REPORT")
    print("=" * 70)
    print(f"Files parsed:       {files_parsed}")
    print(f"Files skipped:      {files_skipped}")
    print(f"Unique products:    {len(products)}")
    print(f"Unique parameters:  {len(unique_params_set)}")
    print(f"Matched to config:  {matched_count}")
    print(f"Unmatched:          {len(deduped_unmatched)}")
    print()

    print("PRODUCTS FOUND:")
    for prod_key in sorted(products.keys()):
        pd = products[prod_key]
        variants = sorted(pd["variants_found"])
        n_params = len(pd["parameters"])
        in_config = "YES" if prod_key in cert_config.get("products", {}) else "NO"
        print(f"  {prod_key:30s}  variants={variants}  params={n_params}  in_config={in_config}")

    if deduped_unmatched:
        print(f"\nUNMATCHED PARAMETERS ({len(deduped_unmatched)}):")
        for u in deduped_unmatched:
            print(f"  {u['name_pl']:50s}  method={u['method']:30s}  products={u['products']}")

    if missing_en:
        print(f"\nPARAMETERS MISSING ENGLISH NAME ({len(missing_en)}):")
        for m in missing_en:
            sug = f" → suggested: {m['suggested_en']}" if m["suggested_en"] else ""
            print(f"  {m['kod']:20s}  {m['current_label']}{sug}")

    # Products in cert_config but not found in templates
    config_products = set(cert_config.get("products", {}).keys())
    extracted_products = set(products.keys())
    missing_from_templates = config_products - extracted_products
    extra_in_templates = extracted_products - config_products
    if missing_from_templates:
        print(f"\nIN CONFIG BUT NOT IN TEMPLATES ({len(missing_from_templates)}):")
        for p in sorted(missing_from_templates):
            print(f"  {p}")
    if extra_in_templates:
        print(f"\nIN TEMPLATES BUT NOT IN CONFIG ({len(extra_in_templates)}):")
        for p in sorted(extra_in_templates):
            print(f"  {p}")

    print(f"\nReport saved to: {OUTPUT_PATH}")
    return output


if __name__ == "__main__":
    main()
