# Cert DB SSOT Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate all certificate data (parameters, variants, product metadata) from cert_config.json to DB as single source of truth, keeping JSON as read-only export.

**Architecture:** Extend `parametry_cert` with name overrides and variant FK. New `cert_variants` table for variant data. Rewrite `generator.py` to read exclusively from DB (no fallback). Rewrite cert editor endpoints to write to DB. Export function regenerates cert_config.json after each save.

**Tech Stack:** SQLite, Flask, python-docx (docxtpl), existing vanilla JS frontend (no changes)

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `mbr/models.py` | Add `cert_variants` table, migrate `parametry_cert` schema |
| Modify | `mbr/certs/generator.py` | Rewrite `build_context()` to DB-only, add `export_cert_config()` |
| Modify | `mbr/certs/routes.py` | Rewrite CRUD endpoints to read/write DB, add export endpoint |
| Create | `scripts/migrate_cert_to_db.py` | One-time migration from cert_config.json → DB |

---

### Task 1: Schema migrations — `cert_variants` table + `parametry_cert` new columns

**Files:**
- Modify: `mbr/models.py` (after line 722, in `init_mbr_tables`)

- [ ] **Step 1: Add `cert_variants` table creation**

In `mbr/models.py`, after the `parametry_cert` CREATE TABLE block (line 722), add:

```python
    # Migration: create cert_variants table
    db.execute("""
        CREATE TABLE IF NOT EXISTS cert_variants (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            produkt       TEXT NOT NULL,
            variant_id    TEXT NOT NULL,
            label         TEXT NOT NULL,
            flags         TEXT DEFAULT '[]',
            spec_number   TEXT,
            opinion_pl    TEXT,
            opinion_en    TEXT,
            avon_code     TEXT,
            avon_name     TEXT,
            remove_params TEXT DEFAULT '[]',
            kolejnosc     INTEGER DEFAULT 0,
            UNIQUE(produkt, variant_id)
        )
    """)
    db.commit()
```

- [ ] **Step 2: Add new columns to `parametry_cert`**

After the cert_variants migration, add column migrations:

```python
    # Migration: add variant_id to parametry_cert (NULL = base product param, NOT NULL = add_parameter for variant)
    try:
        db.execute("ALTER TABLE parametry_cert ADD COLUMN variant_id INTEGER REFERENCES cert_variants(id)")
        db.commit()
    except Exception:
        pass

    # Migration: add name override columns to parametry_cert
    for col in ("name_pl", "name_en", "method"):
        try:
            db.execute(f"ALTER TABLE parametry_cert ADD COLUMN {col} TEXT")
            db.commit()
        except Exception:
            pass
```

- [ ] **Step 3: Verify migrations run**

```bash
cd /Users/tbk/Desktop/aa && python3 -c "
from mbr.db import db_session
from mbr.models import init_mbr_tables
with db_session() as db:
    init_mbr_tables(db)
    # Verify cert_variants exists
    r = db.execute('SELECT count(*) as c FROM cert_variants').fetchone()
    print(f'cert_variants: {r[\"c\"]} rows')
    # Verify new columns exist
    r = db.execute('PRAGMA table_info(parametry_cert)').fetchall()
    cols = [row['name'] for row in r]
    print(f'parametry_cert columns: {cols}')
    assert 'variant_id' in cols
    assert 'name_pl' in cols
    assert 'name_en' in cols
    assert 'method' in cols
    print('OK')
"
```

Expected: `cert_variants: 0 rows`, all 4 new columns present, `OK`.

- [ ] **Step 4: Commit**

```bash
git add mbr/models.py
git commit -m "feat(cert-ssot): add cert_variants table and parametry_cert name override columns"
```

---

### Task 2: Migration script — cert_config.json → DB

**Files:**
- Create: `scripts/migrate_cert_to_db.py`

- [ ] **Step 1: Write migration script**

```python
#!/usr/bin/env python3
"""One-time migration: cert_config.json → DB tables.

Populates cert_variants and updates parametry_cert with name overrides
and variant-specific add_parameters.

Safe to run multiple times (idempotent via INSERT OR IGNORE / upsert logic).
"""
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "mbr" / "cert_config.json"
DB_PATH = PROJECT_ROOT / "data" / "batch_db.sqlite"


def migrate(db_path: Path = DB_PATH, config_path: Path = CONFIG_PATH, dry_run: bool = False):
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)

    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    # Build kod → parametry_analityczne.id lookup
    pa_rows = db.execute("SELECT id, kod FROM parametry_analityczne WHERE aktywny=1").fetchall()
    kod_to_id = {r["kod"]: r["id"] for r in pa_rows}

    stats = {"variants_inserted": 0, "base_params_inserted": 0, "add_params_inserted": 0,
             "params_updated": 0, "products_synced": 0, "skipped": []}

    for prod_key, prod in cfg.get("products", {}).items():
        # 1. Ensure produkty row has metadata
        existing = db.execute("SELECT id FROM produkty WHERE nazwa=?", (prod_key,)).fetchone()
        if existing:
            db.execute(
                "UPDATE produkty SET display_name=?, spec_number=?, cas_number=?, "
                "expiry_months=?, opinion_pl=?, opinion_en=? WHERE nazwa=?",
                (prod.get("display_name", prod_key), prod.get("spec_number", ""),
                 prod.get("cas_number", ""), prod.get("expiry_months", 12),
                 prod.get("opinion_pl", ""), prod.get("opinion_en", ""), prod_key),
            )
        else:
            db.execute(
                "INSERT INTO produkty (nazwa, display_name, spec_number, cas_number, "
                "expiry_months, opinion_pl, opinion_en) VALUES (?,?,?,?,?,?,?)",
                (prod_key, prod.get("display_name", prod_key), prod.get("spec_number", ""),
                 prod.get("cas_number", ""), prod.get("expiry_months", 12),
                 prod.get("opinion_pl", ""), prod.get("opinion_en", "")),
            )
        stats["products_synced"] += 1

        # 2. Base parameters → parametry_cert (variant_id=NULL)
        for i, param in enumerate(prod.get("parameters", [])):
            data_field = param.get("data_field")
            if not data_field or data_field not in kod_to_id:
                # Qualitative param without data_field — try matching by id
                # Skip if no way to map to parametry_analityczne
                if data_field and data_field not in kod_to_id:
                    stats["skipped"].append(f"{prod_key}: param {param.get('id')} data_field={data_field} not in DB")
                    continue
                if not data_field:
                    # Qualitative — try matching by name
                    # For now skip unmapped qualitative params
                    stats["skipped"].append(f"{prod_key}: qualitative param {param.get('id')} has no data_field")
                    continue

            pa_id = kod_to_id[data_field]

            # Check if base binding already exists
            existing_pc = db.execute(
                "SELECT id FROM parametry_cert WHERE produkt=? AND parametr_id=? AND variant_id IS NULL",
                (prod_key, pa_id),
            ).fetchone()

            name_pl = param.get("name_pl") or None
            name_en = param.get("name_en") or None
            method = param.get("method") or None
            requirement = param.get("requirement") or None
            fmt = param.get("format") or "1"
            qr = param.get("qualitative_result") or None

            if existing_pc:
                # Update with name overrides
                db.execute(
                    "UPDATE parametry_cert SET kolejnosc=?, requirement=?, format=?, "
                    "qualitative_result=?, name_pl=?, name_en=?, method=? WHERE id=?",
                    (i, requirement, fmt, qr, name_pl, name_en, method, existing_pc["id"]),
                )
                stats["params_updated"] += 1
            else:
                db.execute(
                    "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, "
                    "format, qualitative_result, variant_id, name_pl, name_en, method) "
                    "VALUES (?,?,?,?,?,?,NULL,?,?,?)",
                    (prod_key, pa_id, i, requirement, fmt, qr, name_pl, name_en, method),
                )
                stats["base_params_inserted"] += 1

        # 3. Variants → cert_variants + add_parameters
        for vi, variant in enumerate(prod.get("variants", [])):
            vid = variant.get("id", "base")
            label = variant.get("label", vid)
            flags = json.dumps(variant.get("flags", []))
            overrides = variant.get("overrides", {})

            # Map remove_parameters (param string ids) to parametry_analityczne.id list
            remove_param_ids = []
            for rp_str_id in overrides.get("remove_parameters", []):
                # Find which data_field this param id maps to
                for p in prod.get("parameters", []):
                    if p.get("id") == rp_str_id and p.get("data_field") in kod_to_id:
                        remove_param_ids.append(kod_to_id[p["data_field"]])
                        break

            remove_params_json = json.dumps(remove_param_ids)

            # Insert or update variant
            existing_cv = db.execute(
                "SELECT id FROM cert_variants WHERE produkt=? AND variant_id=?",
                (prod_key, vid),
            ).fetchone()

            if existing_cv:
                db.execute(
                    "UPDATE cert_variants SET label=?, flags=?, spec_number=?, opinion_pl=?, "
                    "opinion_en=?, avon_code=?, avon_name=?, remove_params=?, kolejnosc=? WHERE id=?",
                    (label, flags, overrides.get("spec_number"), overrides.get("opinion_pl"),
                     overrides.get("opinion_en"), overrides.get("avon_code"),
                     overrides.get("avon_name"), remove_params_json, vi, existing_cv["id"]),
                )
                cv_id = existing_cv["id"]
            else:
                cur = db.execute(
                    "INSERT INTO cert_variants (produkt, variant_id, label, flags, spec_number, "
                    "opinion_pl, opinion_en, avon_code, avon_name, remove_params, kolejnosc) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (prod_key, vid, label, flags, overrides.get("spec_number"),
                     overrides.get("opinion_pl"), overrides.get("opinion_en"),
                     overrides.get("avon_code"), overrides.get("avon_name"),
                     remove_params_json, vi),
                )
                cv_id = cur.lastrowid
                stats["variants_inserted"] += 1

            # 4. Add parameters for this variant
            for api, ap in enumerate(overrides.get("add_parameters", [])):
                ap_df = ap.get("data_field")
                if not ap_df or ap_df not in kod_to_id:
                    stats["skipped"].append(f"{prod_key}/{vid}: add_param {ap.get('id')} data_field={ap_df} not in DB")
                    continue
                ap_pa_id = kod_to_id[ap_df]

                existing_ap = db.execute(
                    "SELECT id FROM parametry_cert WHERE produkt=? AND parametr_id=? AND variant_id=?",
                    (prod_key, ap_pa_id, cv_id),
                ).fetchone()

                ap_name_pl = ap.get("name_pl") or None
                ap_name_en = ap.get("name_en") or None
                ap_method = ap.get("method") or None
                ap_req = ap.get("requirement") or None
                ap_fmt = ap.get("format") or "1"
                ap_qr = ap.get("qualitative_result") or None

                if existing_ap:
                    db.execute(
                        "UPDATE parametry_cert SET kolejnosc=?, requirement=?, format=?, "
                        "qualitative_result=?, name_pl=?, name_en=?, method=? WHERE id=?",
                        (api, ap_req, ap_fmt, ap_qr, ap_name_pl, ap_name_en, ap_method, existing_ap["id"]),
                    )
                else:
                    db.execute(
                        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, "
                        "format, qualitative_result, variant_id, name_pl, name_en, method) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (prod_key, ap_pa_id, api, ap_req, ap_fmt, ap_qr, cv_id,
                         ap_name_pl, ap_name_en, ap_method),
                    )
                    stats["add_params_inserted"] += 1

    if dry_run:
        print("DRY RUN — rolling back")
        db.rollback()
    else:
        db.commit()

    db.close()

    print(f"Products synced:      {stats['products_synced']}")
    print(f"Variants inserted:    {stats['variants_inserted']}")
    print(f"Base params inserted: {stats['base_params_inserted']}")
    print(f"Base params updated:  {stats['params_updated']}")
    print(f"Add params inserted:  {stats['add_params_inserted']}")
    if stats["skipped"]:
        print(f"Skipped ({len(stats['skipped'])}):")
        for s in stats["skipped"]:
            print(f"  {s}")

    return stats


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    migrate(dry_run=dry)
```

- [ ] **Step 2: Run migration (dry-run first)**

```bash
cd /Users/tbk/Desktop/aa && python3 scripts/migrate_cert_to_db.py --dry-run
```

Verify output shows products synced, variants inserted, params inserted. Check skipped list for unexpected items.

- [ ] **Step 3: Run migration for real**

```bash
python3 scripts/migrate_cert_to_db.py
```

- [ ] **Step 4: Verify data**

```bash
python3 -c "
import sqlite3
db = sqlite3.connect('data/batch_db.sqlite')
db.row_factory = sqlite3.Row
cv = db.execute('SELECT COUNT(*) as c FROM cert_variants').fetchone()['c']
pc_base = db.execute('SELECT COUNT(*) as c FROM parametry_cert WHERE variant_id IS NULL').fetchone()['c']
pc_var = db.execute('SELECT COUNT(*) as c FROM parametry_cert WHERE variant_id IS NOT NULL').fetchone()['c']
print(f'cert_variants: {cv}')
print(f'parametry_cert base: {pc_base}')
print(f'parametry_cert variant add_params: {pc_var}')
# Sample one product
rows = db.execute('''
    SELECT pc.kolejnosc, pa.kod, pc.name_pl, pc.name_en, pc.requirement, pc.method, pc.format
    FROM parametry_cert pc
    JOIN parametry_analityczne pa ON pa.id = pc.parametr_id
    WHERE pc.produkt = 'Chegina_K40GLOL' AND pc.variant_id IS NULL
    ORDER BY pc.kolejnosc
''').fetchall()
print(f'\nChegina_K40GLOL base params ({len(rows)}):')
for r in rows:
    print(f'  {r[\"kolejnosc\"]}. {r[\"kod\"]:15} PL={r[\"name_pl\"] or \"(default)\":30} req={r[\"requirement\"]}')
db.close()
"
```

Expected: ~80+ variants, ~150+ base params, variant add_params present.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_cert_to_db.py
git commit -m "feat(cert-ssot): add migration script cert_config.json → DB"
```

---

### Task 3: Generator rewrite — DB-only `build_context()` + export function

**Files:**
- Modify: `mbr/certs/generator.py`

This is the core change. Rewrite `build_context()` to read exclusively from DB. Add `export_cert_config()`. Remove config fallback path.

- [ ] **Step 1: Add `export_cert_config()` function**

Add after `build_preview_context()` (before `_days_in_month`):

```python
def export_cert_config(db) -> dict:
    """Generate cert_config.json structure from DB (read-only export).

    Reads company/footer/rspo from the existing JSON file (rarely changed),
    then builds products/parameters/variants from DB tables.
    """
    # Global settings from file
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            file_cfg = json.load(f)
    except FileNotFoundError:
        file_cfg = {}

    cfg = {
        "company": file_cfg.get("company", {}),
        "footer": file_cfg.get("footer", {}),
        "rspo_number": file_cfg.get("rspo_number", ""),
        "products": {},
    }

    # All products that have cert parameters
    products_with_certs = db.execute(
        "SELECT DISTINCT produkt FROM parametry_cert"
    ).fetchall()

    for prow in products_with_certs:
        prod_key = prow["produkt"]

        # Product metadata
        meta = db.execute(
            "SELECT display_name, spec_number, cas_number, expiry_months, opinion_pl, opinion_en "
            "FROM produkty WHERE nazwa=?", (prod_key,)
        ).fetchone()

        product = {
            "display_name": meta["display_name"] if meta else prod_key,
            "spec_number": (meta["spec_number"] or "") if meta else "",
            "cas_number": (meta["cas_number"] or "") if meta else "",
            "expiry_months": (meta["expiry_months"] or 12) if meta else 12,
            "opinion_pl": (meta["opinion_pl"] or "") if meta else "",
            "opinion_en": (meta["opinion_en"] or "") if meta else "",
        }

        # Base parameters
        params = db.execute(
            "SELECT pc.parametr_id, pc.kolejnosc, pc.requirement, pc.format, "
            "pc.qualitative_result, pc.name_pl, pc.name_en, pc.method, "
            "pa.kod, pa.label, pa.name_en as pa_name_en, pa.method_code "
            "FROM parametry_cert pc "
            "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
            "WHERE pc.produkt=? AND pc.variant_id IS NULL "
            "ORDER BY pc.kolejnosc",
            (prod_key,),
        ).fetchall()

        product["parameters"] = []
        for p in params:
            param = {
                "id": p["kod"],
                "name_pl": p["name_pl"] or p["label"] or "",
                "name_en": p["name_en"] or p["pa_name_en"] or "",
                "requirement": p["requirement"] or "",
                "method": p["method"] or p["method_code"] or "",
                "data_field": p["kod"],
                "format": p["format"] or "1",
            }
            if p["qualitative_result"]:
                param["qualitative_result"] = p["qualitative_result"]
            product["parameters"].append(param)

        # Variants
        variants = db.execute(
            "SELECT * FROM cert_variants WHERE produkt=? ORDER BY kolejnosc",
            (prod_key,),
        ).fetchall()

        product["variants"] = []
        for v in variants:
            variant = {
                "id": v["variant_id"],
                "label": v["label"],
                "flags": json.loads(v["flags"] or "[]"),
            }
            overrides = {}
            if v["spec_number"]:
                overrides["spec_number"] = v["spec_number"]
            if v["opinion_pl"]:
                overrides["opinion_pl"] = v["opinion_pl"]
            if v["opinion_en"]:
                overrides["opinion_en"] = v["opinion_en"]
            if v["avon_code"]:
                overrides["avon_code"] = v["avon_code"]
            if v["avon_name"]:
                overrides["avon_name"] = v["avon_name"]

            # remove_params: convert param IDs back to string ids
            remove_ids = json.loads(v["remove_params"] or "[]")
            if remove_ids:
                remove_strs = []
                for rid in remove_ids:
                    r = db.execute("SELECT kod FROM parametry_analityczne WHERE id=?", (rid,)).fetchone()
                    if r:
                        remove_strs.append(r["kod"])
                if remove_strs:
                    overrides["remove_parameters"] = remove_strs

            # add_parameters for this variant
            add_params = db.execute(
                "SELECT pc.*, pa.kod, pa.label, pa.name_en as pa_name_en, pa.method_code "
                "FROM parametry_cert pc "
                "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
                "WHERE pc.variant_id=? ORDER BY pc.kolejnosc",
                (v["id"],),
            ).fetchall()

            if add_params:
                overrides["add_parameters"] = []
                for ap in add_params:
                    add_p = {
                        "id": ap["kod"],
                        "name_pl": ap["name_pl"] or ap["label"] or "",
                        "name_en": ap["name_en"] or ap["pa_name_en"] or "",
                        "requirement": ap["requirement"] or "",
                        "method": ap["method"] or ap["method_code"] or "",
                        "data_field": ap["kod"],
                        "format": ap["format"] or "1",
                    }
                    if ap["qualitative_result"]:
                        add_p["qualitative_result"] = ap["qualitative_result"]
                    overrides["add_parameters"].append(add_p)

            if overrides:
                variant["overrides"] = overrides
            product["variants"].append(variant)

        cfg["products"][prod_key] = product

    return cfg


def save_cert_config_export(db):
    """Regenerate cert_config.json from DB."""
    cfg = export_cert_config(db)
    tmp = str(_CONFIG_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    import os
    os.replace(tmp, str(_CONFIG_PATH))
```

- [ ] **Step 2: Rewrite `get_variants()` to read from DB**

Replace the existing `get_variants()` function (lines 44-63):

```python
def get_variants(produkt: str) -> list[dict]:
    """Return list of {id, label, flags} for a product from DB."""
    from mbr.db import db_session as _db_session
    key = produkt if "_" in produkt else produkt.replace(" ", "_")
    try:
        with _db_session() as db:
            rows = db.execute(
                "SELECT variant_id, label, flags FROM cert_variants "
                "WHERE produkt=? ORDER BY kolejnosc",
                (key,),
            ).fetchall()
            if not rows:
                # Try with space→underscore
                rows = db.execute(
                    "SELECT variant_id, label, flags FROM cert_variants "
                    "WHERE produkt=? ORDER BY kolejnosc",
                    (produkt.replace(" ", "_"),),
                ).fetchall()
            return [
                {"id": r["variant_id"], "label": r["label"],
                 "flags": json.loads(r["flags"] or "[]")}
                for r in rows
            ]
    except Exception:
        return []
```

- [ ] **Step 3: Rewrite `get_required_fields()` to read from DB**

Replace existing function (lines 69-92):

```python
def get_required_fields(produkt: str, variant_id: str) -> list[str]:
    """Return flags that need user input for a variant."""
    from mbr.db import db_session as _db_session
    key = produkt if "_" in produkt else produkt.replace(" ", "_")
    try:
        with _db_session() as db:
            row = db.execute(
                "SELECT flags, avon_code, avon_name FROM cert_variants "
                "WHERE produkt=? AND variant_id=?",
                (key, variant_id),
            ).fetchone()
            if not row:
                return []
            flags = json.loads(row["flags"] or "[]")
            skip = {"has_rspo"}
            if row["avon_code"]:
                skip.add("has_avon_code")
            if row["avon_name"]:
                skip.add("has_avon_name")
            return [f for f in flags if f not in skip]
    except Exception:
        return []
```

- [ ] **Step 4: Rewrite `build_context()` — DB-only, no fallback**

Replace the entire `build_context()` function (lines 179-402). The new version:

```python
def build_context(
    produkt: str,
    variant_id: str,
    nr_partii: str,
    dt_start,
    wyniki_flat: dict,
    extra_fields: dict | None = None,
    wystawil: str = "",
) -> dict:
    """Build Jinja2 context dict for certificate rendering. Reads exclusively from DB."""
    from mbr.db import db_session as _db_session

    key = produkt if "_" in produkt else produkt.replace(" ", "_")

    with _db_session() as db:
        # 1. Product metadata from produkty table
        meta = db.execute(
            "SELECT display_name, spec_number, cas_number, expiry_months, "
            "opinion_pl, opinion_en FROM produkty WHERE nazwa=?", (key,)
        ).fetchone()
        if not meta:
            raise ValueError(f"Unknown product: {produkt}")

        _display_name = meta["display_name"] or key
        _spec_number = meta["spec_number"] or ""
        _cas_number = meta["cas_number"] or ""
        _expiry_months = meta["expiry_months"] or 12
        _opinion_pl = meta["opinion_pl"] or ""
        _opinion_en = meta["opinion_en"] or ""

        # 2. Variant from cert_variants
        variant_row = db.execute(
            "SELECT * FROM cert_variants WHERE produkt=? AND variant_id=?",
            (key, variant_id),
        ).fetchone()
        if not variant_row:
            raise ValueError(f"Unknown variant '{variant_id}' for product '{produkt}'")

        flags = set(json.loads(variant_row["flags"] or "[]"))
        remove_param_ids = set(json.loads(variant_row["remove_params"] or "[]"))

        # Apply variant overrides
        spec_number = variant_row["spec_number"] or _spec_number
        opinion_pl = variant_row["opinion_pl"] or _opinion_pl
        opinion_en = variant_row["opinion_en"] or _opinion_en

        # 3. Base parameters (variant_id IS NULL)
        base_rows = db.execute(
            "SELECT pc.parametr_id, pc.requirement, pc.format, pc.qualitative_result, "
            "pc.name_pl, pc.name_en, pc.method, "
            "pa.kod, pa.label, pa.name_en as pa_name_en, pa.method_code "
            "FROM parametry_cert pc "
            "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
            "WHERE pc.produkt=? AND pc.variant_id IS NULL "
            "ORDER BY pc.kolejnosc",
            (key,),
        ).fetchall()

        # 4. Filter out removed params
        rows = []
        for r in base_rows:
            if r["parametr_id"] in remove_param_ids:
                continue

            result = ""
            if r["qualitative_result"]:
                result = r["qualitative_result"]
            elif r["kod"] and r["kod"] in wyniki_flat:
                raw = wyniki_flat[r["kod"]]
                if isinstance(raw, dict):
                    val = raw.get("wartosc", raw.get("value", ""))
                else:
                    val = raw
                if val is not None and val != "":
                    try:
                        fmt = r["format"] or "1"
                        result = _format_value(float(val), fmt)
                    except (ValueError, TypeError):
                        result = str(val).replace(".", ",")

            rows.append({
                "name_pl": r["name_pl"] or r["label"] or "",
                "name_en": r["name_en"] or r["pa_name_en"] or "",
                "requirement": r["requirement"] or "",
                "method": r["method"] or r["method_code"] or "",
                "result": result,
            })

        # 5. Add variant-specific parameters
        add_rows = db.execute(
            "SELECT pc.requirement, pc.format, pc.qualitative_result, "
            "pc.name_pl, pc.name_en, pc.method, "
            "pa.kod, pa.label, pa.name_en as pa_name_en, pa.method_code "
            "FROM parametry_cert pc "
            "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
            "WHERE pc.variant_id=? "
            "ORDER BY pc.kolejnosc",
            (variant_row["id"],),
        ).fetchall()

        for r in add_rows:
            result = ""
            if r["qualitative_result"]:
                result = r["qualitative_result"]
            elif r["kod"] and r["kod"] in wyniki_flat:
                raw = wyniki_flat[r["kod"]]
                val = raw.get("wartosc", raw) if isinstance(raw, dict) else raw
                if val is not None and val != "":
                    try:
                        result = _format_value(float(val), r["format"] or "1")
                    except (ValueError, TypeError):
                        result = str(val).replace(".", ",")
            rows.append({
                "name_pl": r["name_pl"] or r["label"] or "",
                "name_en": r["name_en"] or r["pa_name_en"] or "",
                "requirement": r["requirement"] or "",
                "method": r["method"] or r["method_code"] or "",
                "result": result,
            })

    # 6. Calculate dates
    dt_produkcji = ""
    dt_waznosci = ""
    dt_wystawienia = date.today().strftime("%d.%m.%Y")

    if dt_start:
        if isinstance(dt_start, datetime):
            dt_obj = dt_start.date()
        elif isinstance(dt_start, date):
            dt_obj = dt_start
        else:
            try:
                dt_obj = datetime.fromisoformat(str(dt_start)).date()
            except (ValueError, TypeError):
                dt_obj = None

        if dt_obj:
            dt_produkcji = dt_obj.strftime("%d.%m.%Y")
            year = dt_obj.year + (dt_obj.month - 1 + _expiry_months) // 12
            month = (dt_obj.month - 1 + _expiry_months) % 12 + 1
            day = min(dt_obj.day, _days_in_month(year, month))
            dt_waznosci = date(year, month, day).strftime("%d.%m.%Y")

    # 7. Flags and extra fields
    extra = extra_fields or {}
    order_number = extra.get("order_number", "") if "has_order_number" in flags else ""
    certificate_number = extra.get("certificate_number", "") if "has_certificate_number" in flags else ""
    has_rspo = "has_rspo" in flags

    # Read global settings for rspo
    cfg = load_config()
    rspo_number = cfg.get("rspo_number", "CU-RSPO SCC-857488")
    rspo_text = rspo_number if has_rspo else ""
    if has_rspo and "has_certificate_number" not in flags:
        certificate_number = rspo_text
        rspo_text = ""

    avon_code = variant_row["avon_code"] or extra.get("avon_code", "") if "has_avon_code" in flags else ""
    avon_name = variant_row["avon_name"] or extra.get("avon_name", "") if "has_avon_name" in flags else ""

    return {
        "company": cfg.get("company", {}),
        "footer": cfg.get("footer", {}),
        "display_name": _display_name + (" MB" if has_rspo else ""),
        "spec_number": spec_number,
        "cas_number": _cas_number,
        "nr_partii": nr_partii,
        "dt_produkcji": dt_produkcji,
        "dt_waznosci": dt_waznosci,
        "dt_wystawienia": dt_wystawienia,
        "opinion_pl": opinion_pl,
        "opinion_en": opinion_en,
        "rows": rows,
        "order_number": order_number,
        "certificate_number": certificate_number,
        "rspo_text": rspo_text,
        "avon_code": avon_code,
        "avon_name": avon_name,
        "wystawil": wystawil,
    }
```

Note: `load_config()` is still used for `company`/`footer`/`rspo_number` — these global settings remain in the JSON file per spec.

- [ ] **Step 5: Remove old `_build_rows_from_db()` and `_get_product_meta()`**

Delete functions `_build_rows_from_db()` (lines 113-154) and `_get_product_meta()` (lines 160-173). They are replaced by the inline logic in the new `build_context()`.

- [ ] **Step 6: Verify generator compiles**

```bash
python3 -c "from mbr.certs.generator import build_context, export_cert_config, save_cert_config_export; print('OK')"
```

- [ ] **Step 7: Commit**

```bash
git add mbr/certs/generator.py
git commit -m "feat(cert-ssot): rewrite generator to DB-only, add export_cert_config"
```

---

### Task 4: Rewrite cert editor endpoints — DB read/write

**Files:**
- Modify: `mbr/certs/routes.py`

- [ ] **Step 1: Rewrite GET /api/cert/config/products**

Replace `api_cert_config_products()` to read from DB:

```python
@certs_bp.route("/api/cert/config/products")
@role_required("admin")
def api_cert_config_products():
    """List all products that have cert configuration."""
    with db_session() as db:
        rows = db.execute("""
            SELECT p.nazwa as key, p.display_name,
                   (SELECT COUNT(*) FROM parametry_cert pc WHERE pc.produkt=p.nazwa AND pc.variant_id IS NULL) as params_count,
                   (SELECT COUNT(*) FROM cert_variants cv WHERE cv.produkt=p.nazwa) as variants_count
            FROM produkty p
            WHERE EXISTS (SELECT 1 FROM cert_variants cv WHERE cv.produkt=p.nazwa)
            ORDER BY p.display_name
        """).fetchall()
    return jsonify({"ok": True, "products": [dict(r) for r in rows]})
```

- [ ] **Step 2: Rewrite GET /api/cert/config/product/<key>**

```python
@certs_bp.route("/api/cert/config/product/<key>")
@role_required("admin")
def api_cert_config_product_get(key):
    """Full product data from DB for editor."""
    with db_session() as db:
        # Product metadata
        meta = db.execute(
            "SELECT id, display_name, spec_number, cas_number, expiry_months, opinion_pl, opinion_en "
            "FROM produkty WHERE nazwa=?", (key,)
        ).fetchone()
        if not meta:
            return jsonify({"error": "Product not found"}), 404

        # Base parameters
        params = db.execute(
            "SELECT pc.id as pc_id, pc.parametr_id, pc.kolejnosc, pc.requirement, pc.format, "
            "pc.qualitative_result, pc.name_pl, pc.name_en, pc.method, "
            "pa.kod, pa.label, pa.name_en as pa_name_en, pa.method_code "
            "FROM parametry_cert pc "
            "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
            "WHERE pc.produkt=? AND pc.variant_id IS NULL "
            "ORDER BY pc.kolejnosc",
            (key,),
        ).fetchall()

        parameters = []
        for p in params:
            parameters.append({
                "id": p["kod"],
                "name_pl": p["name_pl"] or p["label"] or "",
                "name_en": p["name_en"] or p["pa_name_en"] or "",
                "requirement": p["requirement"] or "",
                "method": p["method"] or p["method_code"] or "",
                "data_field": p["kod"],
                "format": p["format"] or "1",
                "qualitative_result": p["qualitative_result"] or None,
            })

        # Variants
        variant_rows = db.execute(
            "SELECT * FROM cert_variants WHERE produkt=? ORDER BY kolejnosc", (key,)
        ).fetchall()

        variants = []
        for v in variant_rows:
            variant = {
                "id": v["variant_id"],
                "label": v["label"],
                "flags": _json.loads(v["flags"] or "[]"),
                "overrides": {},
            }
            for field in ("spec_number", "opinion_pl", "opinion_en", "avon_code", "avon_name"):
                if v[field]:
                    variant["overrides"][field] = v[field]

            # remove_params → convert IDs to kod strings
            remove_ids = _json.loads(v["remove_params"] or "[]")
            if remove_ids:
                placeholders = ",".join("?" * len(remove_ids))
                rp_rows = db.execute(
                    f"SELECT kod FROM parametry_analityczne WHERE id IN ({placeholders})",
                    remove_ids,
                ).fetchall()
                variant["overrides"]["remove_parameters"] = [r["kod"] for r in rp_rows]

            # add_parameters
            add_params = db.execute(
                "SELECT pc.*, pa.kod, pa.label, pa.name_en as pa_name_en, pa.method_code "
                "FROM parametry_cert pc "
                "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
                "WHERE pc.variant_id=? ORDER BY pc.kolejnosc",
                (v["id"],),
            ).fetchall()
            if add_params:
                variant["overrides"]["add_parameters"] = [{
                    "id": ap["kod"],
                    "name_pl": ap["name_pl"] or ap["label"] or "",
                    "name_en": ap["name_en"] or ap["pa_name_en"] or "",
                    "requirement": ap["requirement"] or "",
                    "method": ap["method"] or ap["method_code"] or "",
                    "data_field": ap["kod"],
                    "format": ap["format"] or "1",
                    "qualitative_result": ap["qualitative_result"] or None,
                } for ap in add_params]

            variants.append(variant)

    product = {
        "display_name": meta["display_name"] or key,
        "spec_number": meta["spec_number"] or "",
        "cas_number": meta["cas_number"] or "",
        "expiry_months": meta["expiry_months"] or 12,
        "opinion_pl": meta["opinion_pl"] or "",
        "opinion_en": meta["opinion_en"] or "",
        "parameters": parameters,
        "variants": variants,
    }

    return jsonify({"ok": True, "product": product, "db_meta": dict(meta)})
```

- [ ] **Step 3: Rewrite PUT /api/cert/config/product/<key>**

```python
@certs_bp.route("/api/cert/config/product/<key>", methods=["PUT"])
@role_required("admin")
def api_cert_config_product_put(key):
    """Save product to DB (single transaction). Regenerate JSON export."""
    data = request.get_json(silent=True) or {}

    with db_session() as db:
        # Verify product exists
        prod = db.execute("SELECT id FROM produkty WHERE nazwa=?", (key,)).fetchone()
        if not prod:
            return jsonify({"error": "Product not found"}), 404

        # kod → parametry_analityczne.id lookup
        pa_rows = db.execute("SELECT id, kod FROM parametry_analityczne WHERE aktywny=1").fetchall()
        kod_to_id = {r["kod"]: r["id"] for r in pa_rows}

        # 1. Update produkty metadata
        for field in ("display_name", "spec_number", "cas_number", "expiry_months", "opinion_pl", "opinion_en"):
            if field in data:
                db.execute(f"UPDATE produkty SET {field}=? WHERE nazwa=?", (data[field], key))

        # 2. Replace base parameters
        parameters = data.get("parameters", [])
        # Validate
        param_ids = set()
        for p in parameters:
            pid = (p.get("id") or "").strip()
            if not pid:
                return jsonify({"error": "Parameter missing id"}), 400
            if pid in param_ids:
                return jsonify({"error": f"Duplicate parameter id: {pid}"}), 400
            param_ids.add(pid)
            if not p.get("name_pl") or not p.get("requirement"):
                return jsonify({"error": f"Parameter '{pid}' missing name_pl or requirement"}), 400
            df = p.get("data_field")
            if df and df not in kod_to_id:
                return jsonify({"error": f"Parameter '{pid}' data_field '{df}' not found in parametry_analityczne"}), 400

        db.execute("DELETE FROM parametry_cert WHERE produkt=? AND variant_id IS NULL", (key,))

        for i, p in enumerate(parameters):
            df = p.get("data_field")
            if not df or df not in kod_to_id:
                continue
            db.execute(
                "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, "
                "format, qualitative_result, variant_id, name_pl, name_en, method) "
                "VALUES (?,?,?,?,?,?,NULL,?,?,?)",
                (key, kod_to_id[df], i, p.get("requirement"),
                 p.get("format") or "1", p.get("qualitative_result"),
                 p.get("name_pl"), p.get("name_en"), p.get("method")),
            )

        # 3. Replace variants
        variants = data.get("variants", [])
        # Delete old variant add_params first (FK dependency)
        old_variant_ids = [r["id"] for r in db.execute(
            "SELECT id FROM cert_variants WHERE produkt=?", (key,)
        ).fetchall()]
        for ov_id in old_variant_ids:
            db.execute("DELETE FROM parametry_cert WHERE variant_id=?", (ov_id,))
        db.execute("DELETE FROM cert_variants WHERE produkt=?", (key,))

        for vi, v in enumerate(variants):
            vid = (v.get("id") or "").strip()
            if not vid or not v.get("label"):
                return jsonify({"error": f"Variant missing id or label"}), 400

            overrides = v.get("overrides", {})
            flags = _json.dumps(v.get("flags", []))

            # Convert remove_parameters (kod strings) to parametry_analityczne IDs
            remove_param_ids = []
            for rp_kod in overrides.get("remove_parameters", []):
                if rp_kod in kod_to_id:
                    remove_param_ids.append(kod_to_id[rp_kod])

            cur = db.execute(
                "INSERT INTO cert_variants (produkt, variant_id, label, flags, spec_number, "
                "opinion_pl, opinion_en, avon_code, avon_name, remove_params, kolejnosc) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (key, vid, v["label"], flags, overrides.get("spec_number"),
                 overrides.get("opinion_pl"), overrides.get("opinion_en"),
                 overrides.get("avon_code"), overrides.get("avon_name"),
                 _json.dumps(remove_param_ids), vi),
            )
            cv_id = cur.lastrowid

            # Add parameters for this variant
            for api, ap in enumerate(overrides.get("add_parameters", [])):
                ap_df = ap.get("data_field")
                if not ap_df or ap_df not in kod_to_id:
                    continue
                db.execute(
                    "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, "
                    "format, qualitative_result, variant_id, name_pl, name_en, method) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (key, kod_to_id[ap_df], api, ap.get("requirement"),
                     ap.get("format") or "1", ap.get("qualitative_result"),
                     cv_id, ap.get("name_pl"), ap.get("name_en"), ap.get("method")),
                )

        db.commit()

        # Regenerate export
        from mbr.certs.generator import save_cert_config_export
        save_cert_config_export(db)

    return jsonify({"ok": True})
```

- [ ] **Step 4: Rewrite POST (create) and DELETE endpoints**

```python
@certs_bp.route("/api/cert/config/product", methods=["POST"])
@role_required("admin")
def api_cert_config_product_create():
    """Create a new product in DB."""
    data = request.get_json(silent=True) or {}
    display_name = (data.get("display_name") or "").strip()
    if not display_name:
        return jsonify({"error": "display_name is required"}), 400

    import re
    key = display_name.replace(" ", "_")
    if not re.match(r'^[A-Za-z0-9_\-]+$', key):
        return jsonify({"error": "Nazwa zawiera niedozwolone znaki (dozwolone: litery, cyfry, _, -)"}), 400

    with db_session() as db:
        existing = db.execute("SELECT id FROM produkty WHERE nazwa=?", (key,)).fetchone()
        if not existing:
            db.execute(
                "INSERT INTO produkty (nazwa, display_name, spec_number, cas_number, "
                "expiry_months, opinion_pl, opinion_en) VALUES (?,?,?,?,?,?,?)",
                (key, display_name, data.get("spec_number", ""), data.get("cas_number", ""),
                 data.get("expiry_months", 12), data.get("opinion_pl", ""), data.get("opinion_en", "")),
            )
        else:
            # Check if already has cert config
            cv = db.execute("SELECT id FROM cert_variants WHERE produkt=?", (key,)).fetchone()
            if cv:
                return jsonify({"error": f"Product '{key}' already has cert configuration"}), 409

        # Create default "base" variant
        db.execute(
            "INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
            "VALUES (?, 'base', ?, '[]', 0)",
            (key, display_name),
        )
        db.commit()

        from mbr.certs.generator import save_cert_config_export
        save_cert_config_export(db)

    return jsonify({"ok": True, "key": key})


@certs_bp.route("/api/cert/config/product/<key>", methods=["DELETE"])
@role_required("admin")
def api_cert_config_product_delete(key):
    """Delete product cert configuration from DB."""
    with db_session() as db:
        cv = db.execute("SELECT id FROM cert_variants WHERE produkt=?", (key,)).fetchone()
        if not cv:
            return jsonify({"error": "Product cert config not found"}), 404

        # Check for issued certificates
        warning = None
        meta = db.execute("SELECT display_name FROM produkty WHERE nazwa=?", (key,)).fetchone()
        display_name = meta["display_name"] if meta else key
        cnt = db.execute(
            "SELECT COUNT(*) as cnt FROM swiadectwa WHERE template_name LIKE ?",
            (f"{display_name}%",),
        ).fetchone()["cnt"]
        if cnt > 0:
            warning = f"Istnieje {cnt} wydanych świadectw. Dane archiwalne pozostają nienaruszone."

        # Delete variant add_params, then variants, then base params
        variant_ids = [r["id"] for r in db.execute(
            "SELECT id FROM cert_variants WHERE produkt=?", (key,)
        ).fetchall()]
        for vid in variant_ids:
            db.execute("DELETE FROM parametry_cert WHERE variant_id=?", (vid,))
        db.execute("DELETE FROM cert_variants WHERE produkt=?", (key,))
        db.execute("DELETE FROM parametry_cert WHERE produkt=?", (key,))
        db.commit()

        from mbr.certs.generator import save_cert_config_export
        save_cert_config_export(db)

    result = {"ok": True}
    if warning:
        result["warning"] = warning
    return jsonify(result)
```

- [ ] **Step 5: Add export endpoint + remove old helpers**

```python
@certs_bp.route("/api/cert/config/export")
@role_required("admin")
def api_cert_config_export():
    """Regenerate and return cert_config.json from DB."""
    with db_session() as db:
        from mbr.certs.generator import save_cert_config_export, export_cert_config
        save_cert_config_export(db)
        cfg = export_cert_config(db)
    return jsonify(cfg)
```

Remove old `_read_config()` and `_write_config()` helper functions (lines 201-215). They are no longer needed.

- [ ] **Step 6: Clean up imports**

Update the import line at top of routes.py. Remove `_CONFIG_PATH` from generator imports (still needed for export path but imported differently). Ensure `build_preview_context`, `_docxtpl_render`, `_gotenberg_convert` are still imported for the preview endpoint.

- [ ] **Step 7: Verify syntax**

```bash
python3 -c "from mbr.certs.routes import *; print('OK')"
```

- [ ] **Step 8: Commit**

```bash
git add mbr/certs/routes.py
git commit -m "feat(cert-ssot): rewrite cert editor endpoints to DB read/write with JSON export"
```

---

### Task 5: Integration verification

**Files:** None (testing only)

- [ ] **Step 1: Verify product list loads**

```bash
python3 -c "
from mbr.db import db_session
from mbr.models import init_mbr_tables
with db_session() as db:
    init_mbr_tables(db)
    rows = db.execute('''
        SELECT p.nazwa, 
               (SELECT COUNT(*) FROM parametry_cert pc WHERE pc.produkt=p.nazwa AND pc.variant_id IS NULL) as pc,
               (SELECT COUNT(*) FROM cert_variants cv WHERE cv.produkt=p.nazwa) as cv
        FROM produkty p
        WHERE EXISTS (SELECT 1 FROM cert_variants cv WHERE cv.produkt=p.nazwa)
        ORDER BY p.nazwa
    ''').fetchall()
    for r in rows:
        print(f'{r[\"nazwa\"]:<25} params={r[\"pc\"]:>2}  variants={r[\"cv\"]:>2}')
    print(f'Total: {len(rows)} products')
"
```

Expected: 30 products with params and variants.

- [ ] **Step 2: Verify build_context produces valid output**

```bash
python3 -c "
from mbr.certs.generator import build_context
ctx = build_context('Chegina_K40GLOL', 'base', '1/2026', '2026-04-09', {})
print(f'display_name: {ctx[\"display_name\"]}')
print(f'spec_number: {ctx[\"spec_number\"]}')
print(f'rows: {len(ctx[\"rows\"])}')
for r in ctx['rows']:
    print(f'  {r[\"name_pl\"]:40} {r[\"name_en\"]:35} {r[\"requirement\"]:15} {r[\"method\"]}')
"
```

Expected: 9 parameter rows matching cert_config.json for Chegina_K40GLOL base variant.

- [ ] **Step 3: Verify export matches original**

```bash
python3 -c "
import json
from mbr.db import db_session
from mbr.certs.generator import export_cert_config

with db_session() as db:
    exported = export_cert_config(db)

# Compare product count
print(f'Exported products: {len(exported[\"products\"])}')

# Sample one product
p = exported['products'].get('Chegina_K40GLOL', {})
print(f'K40GLOL params: {len(p.get(\"parameters\", []))}')
print(f'K40GLOL variants: {len(p.get(\"variants\", []))}')
for v in p.get('variants', []):
    print(f'  {v[\"id\"]}: {v[\"label\"]} flags={v.get(\"flags\",[])}')
"
```

- [ ] **Step 4: Verify variant with overrides**

```bash
python3 -c "
from mbr.certs.generator import build_context
# Loreal MB variant has remove_parameters and spec override
ctx = build_context('Chegina_K40GLOL', 'loreal', '1/2026', '2026-04-09', {})
print(f'display_name: {ctx[\"display_name\"]}')
print(f'spec_number: {ctx[\"spec_number\"]}')
print(f'rows: {len(ctx[\"rows\"])}')
# Should be 7 rows (9 base - 2 removed: dry_matter, h2o)
for r in ctx['rows']:
    print(f'  {r[\"name_pl\"]:40} {r[\"requirement\"]}')
"
```

Expected: 7 rows (dry_matter and h2o removed), spec_number = "P826", display_name ends with " MB".

- [ ] **Step 5: Regenerate cert_config.json export**

```bash
python3 -c "
from mbr.db import db_session
from mbr.certs.generator import save_cert_config_export
with db_session() as db:
    save_cert_config_export(db)
print('Export saved to mbr/cert_config.json')
"
```

- [ ] **Step 6: Commit**

```bash
git add mbr/cert_config.json
git commit -m "data(cert-ssot): regenerate cert_config.json export from DB"
```

---

### Task 6: Manual end-to-end test

- [ ] **Step 1: Start app, navigate to /admin/wzory-cert**

Verify product list loads from DB (not JSON).

- [ ] **Step 2: Edit a product**

1. Click "Chegina K40GLOL"
2. Verify all params and variants load correctly
3. Change a requirement value
4. Click "Zapisz"
5. Verify flash "Zapisano"
6. Verify cert_config.json was regenerated (check file modification time)

- [ ] **Step 3: Test PDF preview**

1. Select "Loreal MB" variant
2. Click "Odśwież podgląd"
3. Verify PDF renders (requires Gotenberg at localhost:3000)

- [ ] **Step 4: Test create/delete product**

1. Create "Test Product"
2. Verify DB has produkty row + cert_variants "base" row
3. Delete "Test Product"
4. Verify cleaned up

- [ ] **Step 5: Test certificate generation**

If there's an existing EBR with wyniki, generate a real certificate via the lab UI to verify the generator works end-to-end with DB-only path.

- [ ] **Step 6: Commit any fixes**

```bash
git add -A && git commit -m "fix(cert-ssot): integration test fixes"
```
