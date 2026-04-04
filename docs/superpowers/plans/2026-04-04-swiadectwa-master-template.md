# Świadectwa Master Template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 86 .docx certificate templates with one HTML master template driven by JSON config, generating pixel-perfect PDFs via weasyprint.

**Architecture:** `cert_config.json` (all products/variants/parameters) → `cert_gen_v2.py` (loads config, merges with ebr_wyniki data) → `cert_master.html` (Jinja2 master) → weasyprint → PDF. Existing endpoints modified in-place, old system kept as fallback.

**Tech Stack:** Python 3, Flask, Jinja2, weasyprint, SQLite3

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `mbr/cert_config.json` | CREATE | All product definitions, parameters, variants, qualitative fields |
| `mbr/cert_gen_v2.py` | CREATE | Load config, build context, render HTML→PDF, save PDF |
| `mbr/templates/pdf/cert_master.html` | CREATE | Jinja2 HTML master template for all certificates |
| `mbr/app.py` | MODIFY (lines 525-581) | Switch endpoints to use cert_gen_v2 + handle extra_fields |
| `mbr/templates/laborant/_fast_entry_content.html` | MODIFY (lines 754-818, 845-864) | Popup for required fields, updated generate flow |
| `mbr/seed_mbr.py` | MODIFY | Add missing parameters (barwa_hz, wolna_amina, etc.) |

---

### Task 1: Create cert_config.json — Product Registry

**Files:**
- Create: `mbr/cert_config.json`

This is the single source of truth for all certificate generation. Contains company info, all 31 products, their parameters, and all ~86 variant definitions.

- [ ] **Step 1: Create cert_config.json with company/footer + first product (Chegina K40GLOL)**

Create `mbr/cert_config.json`:

```json
{
  "company": {
    "name": "PPU Chemco Spółka z o.o.",
    "address": "ul. Kościuszki 19, 83-033 Sobowidz",
    "email": "biuro@chemco.pl",
    "bdo": "000003546"
  },
  "footer": {
    "country_pl": "Polska",
    "country_en": "Poland",
    "issuer_pl": "Specjalista ds. KJ",
    "issuer_en": "Quality Control Specialist",
    "clause_pl": "Dokument utworzony elektronicznie, nie wymaga podpisu.",
    "clause_en": "The certificate is not signed as it is electronically edited."
  },
  "products": {
    "Chegina_K40GLOL": {
      "display_name": "Chegina K40GLOL",
      "spec_number": "P833",
      "cas_number": "147170-44-3",
      "expiry_months": 12,
      "opinion_pl": "Produkt odpowiada wymaganiom P833",
      "opinion_en": "The product complies with P833",
      "parameters": [
        {
          "id": "barwa_hz",
          "name_pl": "Barwa w skali Hazena",
          "name_en": "Colour (Hazen scale)",
          "requirement": "max 150",
          "method": "L928",
          "data_field": "barwa_hz",
          "format": "0"
        },
        {
          "id": "odour",
          "name_pl": "Zapach",
          "name_en": "Odour",
          "requirement": "słaby /faint",
          "method": "organoleptycznie /organoleptic",
          "data_field": null,
          "qualitative_result": "zgodny /right"
        },
        {
          "id": "appearance",
          "name_pl": "Wygląd",
          "name_en": "Appearance",
          "requirement": "klarowna ciecz /clear liquid",
          "method": "organoleptycznie /organoleptic",
          "data_field": null,
          "qualitative_result": "zgodny /right"
        },
        {
          "id": "ph",
          "name_pl": "pH (20°C)",
          "name_en": "pH (20°C)",
          "requirement": "4,50-5,50",
          "method": "L905",
          "data_field": "ph_10proc",
          "format": "2"
        },
        {
          "id": "active_matter",
          "name_pl": "Substancja aktywna [%]",
          "name_en": "Active matter [%]",
          "requirement": "37,0-42,0",
          "method": "L932",
          "data_field": "sa",
          "format": "1"
        },
        {
          "id": "nacl",
          "name_pl": "NaCl [%]",
          "name_en": "NaCl [%]",
          "requirement": "5,8\u20137,3",
          "method": "L941",
          "data_field": "nacl",
          "format": "1"
        },
        {
          "id": "dry_matter",
          "name_pl": "Sucha masa [%]",
          "name_en": "Dry matter [%]",
          "requirement": "min. 44,0",
          "method": "L903",
          "data_field": "sm",
          "format": "1"
        },
        {
          "id": "h2o",
          "name_pl": "H2O [%]",
          "name_en": "H2O [%]",
          "requirement": "52,0 \u2013 56,0",
          "method": "L903",
          "data_field": "h2o",
          "format": "1"
        },
        {
          "id": "free_amine",
          "name_pl": "Wolna kokamidopropylodimetyloamina [%]",
          "name_en": "Free cocamidopropyldimethylamine [%]",
          "requirement": "max 0,30",
          "method": "L904",
          "data_field": "wolna_amina",
          "format": "2"
        }
      ],
      "variants": [
        {
          "id": "base",
          "label": "Chegina K40GLOL",
          "flags": []
        },
        {
          "id": "loreal",
          "label": "Chegina K40GLOL \u2014 Loreal MB",
          "flags": ["has_certificate_number", "has_rspo"],
          "overrides": {
            "spec_number": "P826",
            "opinion_pl": "Produkt odpowiada wymaganiom P826",
            "opinion_en": "The product complies with P826"
          }
        },
        {
          "id": "loreal_belgia",
          "label": "Chegina K40GLOL \u2014 Loreal Belgia MB",
          "flags": ["has_order_number", "has_certificate_number", "has_rspo"],
          "overrides": {
            "spec_number": "P826",
            "opinion_pl": "Produkt odpowiada wymaganiom P826",
            "opinion_en": "The product complies with P826"
          }
        },
        {
          "id": "loreal_wlochy",
          "label": "Chegina K40GLOL \u2014 Loreal W\u0142ochy MB",
          "flags": ["has_order_number", "has_certificate_number", "has_rspo"],
          "overrides": {
            "spec_number": "P826",
            "opinion_pl": "Produkt odpowiada wymaganiom P826",
            "opinion_en": "The product complies with P826"
          }
        },
        {
          "id": "kosmepol",
          "label": "Chegina K40GLOL \u2014 Kosmepol MB",
          "flags": ["has_order_number", "has_certificate_number", "has_rspo"],
          "overrides": {
            "spec_number": "P826",
            "opinion_pl": "Produkt odpowiada wymaganiom P826",
            "opinion_en": "The product complies with P826"
          }
        }
      ]
    }
  }
}
```

- [ ] **Step 2: Add all remaining 30 products**

Add every product from the analysis document (`docs/superpowers/specs/2026-04-04-wzory-swiadectw-analiza.md` section 3). Use same structure as K40GLOL above. Full product list to add:

**Betainy:**
- `Chegina_K40GLO` — spec P825, CAS 147170-44-3, params: sm, nacl, barwa_hz, ph_10proc, sa, gestosc. Variants: base, MB, NR_ZAM, MB+NR_ZAM
- `Chegina_K40GL` — spec P827, CAS 1334422-09-1, params: sm, nacl, barwa_hz, ph_10proc, sa. Variants: base, MB, NR_ZAM, ADAM&PARTNER (adds h2o2 param)
- `Chegina_K40GLN` — spec P836, CAS 1334422-09-1, params: barwa_hz, odour, appearance, ph, sa, nacl, sm, h2o, wolna_amina. Variants: base, MB
- `Chegina_K40GLOS` — spec P834, CAS 147170-44-3, params: barwa_hz, odour, appearance, ph, sa, nacl, sm, h2o, wolna_amina. Variants: base, MB
- `Chegina_GLOL40` — spec P826, CAS 147170-44-3, params: colour_desc, odour, appearance, ph, sa, wolna_amina. Variants: base, MB, NR_ZAM, OQEMA (adds nacl, h2o)
- `Chegina_K7` — spec P819, CAS 1334422-09-1, params: sm, nd20, barwa_jodowa, sa. Variants: base, MB, NR_ZAM, ADAM&PARTNER (adds h2o2), DR_MIELE
- `Chegina_K7B` — spec P837, params: sm, barwa_jodowa, sa. Variants: base, MB, NR_ZAM
- `Chegina_KK` — spec P818, params: odour, appearance, ph_10proc, nacl, sa, wolna_amina, barwa_jodowa, mca, dca, dmapa. Variants: base, AVON, LEHVOSS, PRIME, REVADA, SKINCHEM
- `Chegina_CC` — spec P828, CAS 66455-29-6, params: appearance, barwa_hz, odour, ph, sa, alkalicznosc. Variant: base
- `Chegina_CCR` — spec P829, CAS 66455-29-6, params: appearance, barwa_hz, odour, ph, sa. Variant: base

**Amidy:**
- `Chelamid_DK` — spec P816, CAS 68155-07-7, params: dea, barwa_jodowa, ph. Variants: base, MB, NR_ZAM, MB+NR_ZAM, PELNA, PELNA+NR_ZAM, ELIN (adds dietanolamina, form)
- `Monamid_KO` — spec P833, CAS 69227-24-3, params: barwa_gardner, odour, appearance, wkt, mea, estry. Variants: base, NR_ZAM, AVON (adds gliceryna, fatty_acid_dist), GHP (colour max 6)
- `Monamid_K` — spec P824, params: barwa_jodowa, wkt, mea, estry. Variant: base

**Cheminox:**
- `Cheminox_K` — spec P822, CAS 1471314-81-4, params: sm, sa, barwa_jodowa. Variants: base, MB, NR_ZAM
- `Cheminox_K35` — spec P835, CAS 1471314-81-4, params: sm, sa, barwa_jodowa. Variants: base, NR_ZAM

**Alkohole/amidoaminy:**
- `Alkinol` — spec P801, params: barwa_jodowa, odour, appearance, lk, lz, t_kropl, lh. Variant: base
- `Alkinol_B` — spec P801, params: barwa_jodowa, odour, appearance, lk, lz, t_kropl, lh, li. Variants: base, MB, AVON
- `Alstermid_K` — spec P806, CAS 7651-02-7, params: lk, la. Variant: base

**Estry:**
- `Glikoster_P` — spec P804, CAS 1323-39-3, params: barwa_jodowa, odour, appearance, lk, wolny_glikol, lh, monoestry. Variants: base, AVON (adds fatty_acid_dist)
- `Dister_E` — spec P805, CAS 91031-31-1, params: lk, wolny_glikol_etyl, lh, lz, t_topn. Variant: base
- `Monester_O` — spec P802, CAS 68424-61-3, params: lk, lz, nd20, li. Variant: base
- `Monester_S` — spec P803, CAS 31566-31-1, params: lk, t_kropl, lz, li. Variant: base
- `Citrowax` — spec P808, CAS 7775-50-0, params: lk, t_kropl. Variant: base

**Inne:**
- `Perlico_45` — spec P809, params: sm, ph. Variants: base, NR_ZAM, REUSE
- `Chemal_CS3070` — CAS 67762-27-0, params: lh, lk, lz, li, c16, c18. Variants: base, MB, NR_ZAM
- `Chemal_CS5050` — CAS 67762-27-0, params: lh, lk, lz, li, c16, c18 (diff values). Variant: MB
- `HSH_CS3070` — CAS 67762-27-0, params: lh, lk, lz, li, c16, c18 (diff methods). Variants: base, MB
- `SLES` — spec P834, params: colour_desc, ph, sa. Variant: base
- `Kwas_stearynowy` — spec P830, CAS 67701-03-5, params: lk, t_kropl, li. Variant: base

Use the exact parameter names, requirements, and methods from `docs/superpowers/specs/2026-04-04-wzory-swiadectw-analiza.md` section 3.

For each product's `data_field` mapping, use these codes that match `seed_mbr.py`:
- `sm` → dry matter, `nacl` → NaCl, `ph_10proc` → pH, `nd20` → refraction
- `sa` → active matter, `aa` → amino acidity, `so3` → sulfites, `h2o2` → peroxides
- `barwa_fau` → colour FAU, `barwa_hz` → colour Hazen
- `gestosc` → density, `wolna_amina` → free amine
- `lk` → acid value, `lz` → saponification, `li` → iodine value, `lh` → hydroxyl value
- `la` → amine value, `t_kropl` → dropping point, `t_topn` → melting point
- `wkt` → free fatty acids, `mea` → MEA, `estry` → esters
- `wolny_glikol` → free glycol, `monoestry` → monoesters
- `dea` → DEA, `dietanolamina` → diethanolamide, `alkalicznosc` → alkalinity
- Qualitative fields (`data_field: null`) use `qualitative_result` instead

- [ ] **Step 3: Validate JSON structure**

Run:
```bash
python3 -c "import json; d=json.load(open('mbr/cert_config.json')); print(f'Products: {len(d[\"products\"])}'); total_v=sum(len(p[\"variants\"]) for p in d[\"products\"].values()); print(f'Variants: {total_v}')"
```

Expected: Products: 31, Variants: ~86

- [ ] **Step 4: Commit**

```bash
git add mbr/cert_config.json
git commit -m "feat: add cert_config.json — single source of truth for all certificate templates

Replaces 86 .docx template files + cert_mappings.py with one JSON config.
Contains 31 products, ~86 variants, all parameters, requirements, and methods."
```

---

### Task 2: Create cert_gen_v2.py — Generation Engine

**Files:**
- Create: `mbr/cert_gen_v2.py`

- [ ] **Step 1: Create cert_gen_v2.py with load_config and get_variants**

Create `mbr/cert_gen_v2.py`:

```python
"""Certificate generation engine v2 — JSON config + HTML master template."""

import json
from datetime import date, datetime
from pathlib import Path

from flask import render_template

_CONFIG_PATH = Path(__file__).parent / "cert_config.json"
_config_cache: dict | None = None


def load_config(*, reload: bool = False) -> dict:
    """Load cert_config.json (cached after first call)."""
    global _config_cache
    if _config_cache is None or reload:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            _config_cache = json.load(f)
    return _config_cache


def get_variants(produkt: str) -> list[dict]:
    """Return list of variant dicts for a product.

    Each dict: {id, label, flags, overrides?}
    Used by the UI to show the template picker.
    """
    cfg = load_config()
    product_key = produkt.replace(" ", "_")
    product = cfg["products"].get(product_key)
    if not product:
        return []
    return [
        {"id": v["id"], "label": v["label"], "flags": v.get("flags", [])}
        for v in product["variants"]
    ]


def get_required_fields(produkt: str, variant_id: str) -> list[str]:
    """Return list of flags that require user input for a variant.

    Possible flags: has_order_number, has_certificate_number,
                    has_avon_code, has_avon_name
    """
    cfg = load_config()
    product_key = produkt.replace(" ", "_")
    product = cfg["products"].get(product_key)
    if not product:
        return []
    for v in product["variants"]:
        if v["id"] == variant_id:
            return [f for f in v.get("flags", []) if f != "has_rspo"]
    return []
```

- [ ] **Step 2: Add build_context function**

Append to `mbr/cert_gen_v2.py`:

```python
def _format_value(value: float, fmt: str) -> str:
    """Format a numeric value with Polish decimal comma.

    fmt is the number of decimal places as a string: "0", "1", "2", "3".
    """
    try:
        precision = int(fmt)
        formatted = f"{value:.{precision}f}"
    except (ValueError, TypeError):
        formatted = str(value)
    return formatted.replace(".", ",")


def build_context(
    produkt: str,
    variant_id: str,
    nr_partii: str,
    dt_start: str | None,
    wyniki_flat: dict,
    extra_fields: dict | None = None,
) -> dict:
    """Build the Jinja2 template context for rendering a certificate.

    Args:
        produkt: product key (e.g. "Chegina_K40GLOL")
        variant_id: variant id (e.g. "base", "loreal")
        nr_partii: batch number (e.g. "24/2026")
        dt_start: production start date ISO string
        wyniki_flat: {kod: row_dict_or_value} from ebr_wyniki
        extra_fields: {order_number, certificate_number, avon_code, avon_name}

    Returns:
        dict ready for Jinja2 render of cert_master.html
    """
    cfg = load_config()
    product_key = produkt.replace(" ", "_")
    product = cfg["products"][product_key]
    extra = extra_fields or {}

    # Find variant and apply overrides
    variant = None
    for v in product["variants"]:
        if v["id"] == variant_id:
            variant = v
            break
    if variant is None:
        variant = product["variants"][0]

    overrides = variant.get("overrides", {})
    spec_number = overrides.get("spec_number", product["spec_number"])
    opinion_pl = overrides.get("opinion_pl", product["opinion_pl"])
    opinion_en = overrides.get("opinion_en", product["opinion_en"])

    # Resolve parameter list — apply add/remove overrides
    base_params = list(product["parameters"])
    if "remove_parameters" in overrides:
        remove_ids = set(overrides["remove_parameters"])
        base_params = [p for p in base_params if p["id"] not in remove_ids]
    if "add_parameters" in overrides:
        base_params.extend(overrides["add_parameters"])

    # Build parameter rows
    rows = []
    for param in base_params:
        row = {
            "name_pl": param["name_pl"],
            "name_en": param["name_en"],
            "requirement": param["requirement"],
            "method": param["method"],
            "result": "",
        }
        if param.get("qualitative_result"):
            row["result"] = param["qualitative_result"]
        elif param.get("data_field"):
            kod = param["data_field"]
            val_entry = wyniki_flat.get(kod)
            if val_entry is not None:
                # val_entry can be a row dict or a raw value
                if isinstance(val_entry, dict):
                    raw = val_entry.get("wartosc")
                else:
                    raw = val_entry
                if raw is not None:
                    try:
                        num = float(raw)
                        row["result"] = _format_value(num, param.get("format", "2"))
                    except (ValueError, TypeError):
                        row["result"] = str(raw).replace(".", ",")
        rows.append(row)

    # Dates
    dt_produkcji = ""
    dt_waznosci = ""
    if dt_start:
        try:
            dt = datetime.fromisoformat(str(dt_start))
            dt_produkcji = dt.strftime("%d.%m.%Y")
            expiry_months = product.get("expiry_months", 12)
            expiry_year = dt.year + (dt.month + expiry_months - 1) // 12
            expiry_month = (dt.month + expiry_months - 1) % 12 + 1
            dt_waznosci = dt.replace(year=expiry_year, month=expiry_month).strftime(
                "%d.%m.%Y"
            )
        except (ValueError, AttributeError):
            dt_produkcji = str(dt_start)[:10]
    dt_wystawienia = date.today().strftime("%d.%m.%Y")

    # Flags
    flags = set(variant.get("flags", []))

    return {
        "company": cfg["company"],
        "footer": cfg["footer"],
        "display_name": product["display_name"],
        "spec_number": spec_number,
        "cas_number": product.get("cas_number", ""),
        "nr_partii": nr_partii,
        "dt_produkcji": dt_produkcji,
        "dt_waznosci": dt_waznosci,
        "dt_wystawienia": dt_wystawienia,
        "opinion_pl": opinion_pl,
        "opinion_en": opinion_en,
        "rows": rows,
        # Optional fields
        "order_number": extra.get("order_number", "") if "has_order_number" in flags else "",
        "certificate_number": extra.get("certificate_number", "") if "has_certificate_number" in flags else "",
        "has_rspo": "has_rspo" in flags,
        "avon_code": extra.get("avon_code", "") if "has_avon_code" in flags else "",
        "avon_name": extra.get("avon_name", "") if "has_avon_name" in flags else "",
    }
```

- [ ] **Step 3: Add generate and save functions**

Append to `mbr/cert_gen_v2.py`:

```python
def generate_certificate_pdf(
    produkt: str,
    variant_id: str,
    nr_partii: str,
    dt_start: str | None,
    wyniki_flat: dict,
    extra_fields: dict | None = None,
) -> bytes:
    """Generate certificate PDF bytes.

    Returns:
        PDF file content as bytes.
    """
    from weasyprint import HTML

    ctx = build_context(produkt, variant_id, nr_partii, dt_start, wyniki_flat, extra_fields)
    html = render_template("pdf/cert_master.html", **ctx)
    return HTML(string=html).write_pdf()


# Re-use save logic from cert_gen.py
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "swiadectwa"


def save_certificate_pdf(
    pdf_bytes: bytes, produkt: str, variant_label: str, nr_partii: str
) -> str:
    """Save PDF to data/swiadectwa/{year}/{product}/{variant}_{nr}.pdf.

    Returns:
        Relative path string (relative to project root).
    """
    year = date.today().year
    product_slug = produkt.replace(" ", "_")
    # Clean variant label for filename
    label_safe = variant_label.replace(" ", "_").replace("/", "_").replace("\\", "_")
    label_safe = label_safe.replace("\u2014", "-").replace("—", "-")
    nr_safe = nr_partii.replace("/", "_").replace("\\", "_").replace(" ", "_")
    pdf_name = f"{label_safe}_{nr_safe}.pdf"

    out_dir = OUTPUT_DIR / str(year) / product_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / pdf_name
    out_path.write_bytes(pdf_bytes)

    return str(out_path.relative_to(Path(__file__).resolve().parent.parent))
```

- [ ] **Step 4: Verify module loads without errors**

Run:
```bash
cd /Users/tbk/Desktop/aa && python3 -c "from mbr.cert_gen_v2 import load_config, get_variants, get_required_fields; cfg = load_config(); print('OK, products:', len(cfg['products'])); v = get_variants('Chegina_K40GLOL'); print('Variants:', [x['label'] for x in v]); f = get_required_fields('Chegina_K40GLOL', 'loreal_belgia'); print('Required fields:', f)"
```

Expected:
```
OK, products: 31
Variants: ['Chegina K40GLOL', 'Chegina K40GLOL — Loreal MB', ...]
Required fields: ['has_order_number', 'has_certificate_number']
```

- [ ] **Step 5: Commit**

```bash
git add mbr/cert_gen_v2.py
git commit -m "feat: add cert_gen_v2.py — config-driven certificate generation engine"
```

---

### Task 3: Create cert_master.html — Master Template

**Files:**
- Create: `mbr/templates/pdf/cert_master.html`

- [ ] **Step 1: Create the master HTML template**

Create `mbr/templates/pdf/cert_master.html`. This must produce output visually matching the existing `swiadectwo.html` (same CSS structure) but driven entirely by the context dict from `build_context()`:

```html
<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<style>
@page {
  size: A4;
  margin: 20mm 18mm;
}
body {
  font-family: 'Times New Roman', Times, serif;
  font-size: 10pt;
  color: #000;
  margin: 0;
  padding: 0;
}

/* Header */
.cert-header {
  display: table;
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 10pt;
}
.cert-header-logo {
  display: table-cell;
  width: 35%;
  vertical-align: middle;
  font-size: 13pt;
  font-weight: bold;
}
.cert-header-logo .company-sub {
  font-size: 8pt;
  font-weight: normal;
  margin-top: 2pt;
}
.cert-header-title {
  display: table-cell;
  text-align: center;
  vertical-align: middle;
  padding: 4pt 8pt;
}
.cert-header-title .cert-title-main {
  font-size: 13pt;
  font-weight: bold;
  display: block;
}
.cert-header-title .cert-title-sub {
  font-size: 10pt;
  font-style: italic;
  display: block;
}
.cert-header-title .cert-product {
  font-size: 12pt;
  font-weight: bold;
  margin-top: 4pt;
  display: block;
}
.cert-header-tds {
  display: table-cell;
  width: 25%;
  text-align: right;
  vertical-align: top;
  font-size: 8.5pt;
}
hr.cert-divider {
  border: none;
  border-top: 2px solid #000;
  margin: 6pt 0 10pt 0;
}

/* AVON fields */
.avon-fields {
  font-size: 9.5pt;
  margin-bottom: 6pt;
}
.avon-fields p {
  margin: 1pt 0;
}

/* Meta table */
table.meta-table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 10pt;
  font-size: 9.5pt;
}
table.meta-table td {
  padding: 3pt 6pt;
  border: 1px solid #000;
}
table.meta-table td.meta-label {
  font-weight: bold;
  width: 30%;
  background: #f5f5f5;
}

/* Results table */
table.results-table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 12pt;
  font-size: 9.5pt;
}
table.results-table th {
  border: 1px solid #000;
  padding: 4pt 6pt;
  background: #ececec;
  font-weight: bold;
  text-align: center;
  font-size: 9pt;
}
table.results-table td {
  border: 1px solid #000;
  padding: 3pt 6pt;
  vertical-align: middle;
}
table.results-table td.col-param { width: 38%; }
table.results-table td.col-req { width: 22%; text-align: center; }
table.results-table td.col-method { width: 18%; text-align: center; font-size: 8.5pt; }
table.results-table td.col-result { width: 22%; text-align: center; font-weight: bold; }
table.results-table td.col-result.empty-result { color: #777; font-weight: normal; }

/* Opinion */
.opinion-section { margin: 10pt 0; font-size: 9.5pt; }
.opinion-section .opinion-label { font-weight: bold; margin-bottom: 3pt; }
.opinion-text { padding: 4pt 6pt; border-left: 3px solid #000; margin-left: 4pt; }

/* Footer */
.cert-footer { margin-top: 18pt; font-size: 9pt; }
.cert-footer-date { margin-bottom: 16pt; }
.cert-footer-sig { display: table; width: 100%; }
.cert-footer-sig-left { display: table-cell; width: 50%; vertical-align: top; }
.cert-footer-sig-right { display: table-cell; width: 50%; vertical-align: top; text-align: right; }
.sig-line { margin-top: 30pt; border-top: 1px solid #000; padding-top: 3pt; font-size: 8.5pt; width: 160pt; }
.sig-line-right { margin-top: 30pt; border-top: 1px solid #000; padding-top: 3pt; font-size: 8.5pt; width: 160pt; margin-left: auto; }
.electronic-notice { margin-top: 14pt; font-size: 8pt; font-weight: bold; border-top: 1px solid #ccc; padding-top: 5pt; }
.electronic-notice-sub { font-size: 7.5pt; font-weight: normal; font-style: italic; margin-top: 2pt; }
</style>
</head>
<body>

<!-- Header -->
<div class="cert-header">
  <div class="cert-header-logo">
    {{ company.name }}
    <div class="company-sub">{{ company.address }}<br>e-mail: {{ company.email }}<br>BDO: {{ company.bdo }}</div>
  </div>
  <div class="cert-header-title">
    <span class="cert-title-main">ŚWIADECTWO JAKOŚCI</span>
    <span class="cert-title-sub">/ CERTIFICATE OF ANALYSIS</span>
    <span class="cert-product">{{ display_name }}</span>
  </div>
  <div class="cert-header-tds">
    {% if spec_number %}Klasyfikowany na podstawie specyfikacji<br>/ Classified on TDS: {{ spec_number }}<br>{% endif %}
    {% if cas_number %}CAS: {{ cas_number }}{% endif %}
  </div>
</div>
<hr class="cert-divider">

<!-- AVON fields (conditional) -->
{% if avon_code %}
<div class="avon-fields">
  <p><strong>AVON code:</strong> {{ avon_code }}</p>
  <p><strong>AVON name:</strong> {{ avon_name }}</p>
</div>
{% endif %}

<!-- Metadata Table -->
<table class="meta-table">
  <tr>
    <td class="meta-label">Partia / Batch</td>
    <td>{{ nr_partii }}</td>
    <td class="meta-label">Kraj pochodzenia / Country of origin</td>
    <td>{{ footer.country_pl }} / {{ footer.country_en }}</td>
  </tr>
  <tr>
    <td class="meta-label">Data produkcji / Production date</td>
    <td>{{ dt_produkcji }}</td>
    <td class="meta-label">Data ważności / Expiry date</td>
    <td>{{ dt_waznosci }}</td>
  </tr>
  {% if order_number %}
  <tr>
    <td class="meta-label">Numer zamówienia / Order No.</td>
    <td colspan="3">{{ order_number }}</td>
  </tr>
  {% endif %}
  {% if certificate_number %}
  <tr>
    <td class="meta-label">Numer certyfikatu / Certificate No.</td>
    <td colspan="3">{{ certificate_number }}{% if has_rspo %} &nbsp; CU-RSPO SCC-857488{% endif %}</td>
  </tr>
  {% endif %}
</table>

<!-- Results Table -->
<table class="results-table">
  <thead>
    <tr>
      <th>Parametr oznaczany<br><em>/ Inspection characteristic</em></th>
      <th>Wymagania<br><em>/ Requirement</em></th>
      <th>Metoda badań<br><em>/ Test method</em></th>
      <th>Wynik<br><em>/ Result</em></th>
    </tr>
  </thead>
  <tbody>
    {% for row in rows %}
    <tr>
      <td class="col-param">{{ row.name_pl }}<br><em>/ {{ row.name_en }}</em></td>
      <td class="col-req">{{ row.requirement }}</td>
      <td class="col-method">{{ row.method }}</td>
      {% if row.result %}
        <td class="col-result">{{ row.result }}</td>
      {% else %}
        <td class="col-result empty-result">—</td>
      {% endif %}
    </tr>
    {% endfor %}
  </tbody>
</table>

<!-- Opinion -->
<div class="opinion-section">
  <div class="opinion-label">Opinia Laboratorium KJ / Opinion of Quality Control Laboratory:</div>
  <div class="opinion-text">
    {{ opinion_pl }}<br>
    <em>/ {{ opinion_en }}</em>
  </div>
</div>

<!-- Footer -->
<div class="cert-footer">
  <div class="cert-footer-date">Sobowidz, {{ dt_wystawienia }}</div>
  <div class="cert-footer-sig">
    <div class="cert-footer-sig-left">
      <div class="sig-line">Wystawił / The certificate made by</div>
    </div>
    <div class="cert-footer-sig-right">
      <div class="sig-line-right">{{ footer.issuer_pl }} / {{ footer.issuer_en }}</div>
    </div>
  </div>
  <div class="electronic-notice">
    {{ footer.clause_pl }}
    <div class="electronic-notice-sub">/ {{ footer.clause_en }}</div>
  </div>
</div>

</body>
</html>
```

- [ ] **Step 2: Smoke test — render a certificate with mock data**

Run:
```bash
cd /Users/tbk/Desktop/aa && python3 -c "
import sys; sys.path.insert(0, '.')
from mbr.app import app
from mbr.cert_gen_v2 import build_context
from weasyprint import HTML

with app.app_context():
    ctx = build_context(
        'Chegina_K40GLOL', 'base', '24/2026', '2026-03-15',
        {'barwa_hz': 45, 'ph_10proc': 4.95, 'sa': 39.2, 'nacl': 6.5, 'sm': 45.1, 'h2o': 54.2, 'wolna_amina': 0.12},
    )
    from flask import render_template
    html = render_template('pdf/cert_master.html', **ctx)
    pdf = HTML(string=html).write_pdf()
    open('/tmp/test_cert.pdf', 'wb').write(pdf)
    print(f'OK — wrote {len(pdf)} bytes to /tmp/test_cert.pdf')
"
```

Expected: `OK — wrote NNNN bytes to /tmp/test_cert.pdf`
Open `/tmp/test_cert.pdf` to visually verify layout matches original .docx certificates.

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/pdf/cert_master.html
git commit -m "feat: add cert_master.html — single Jinja2 template for all certificates"
```

---

### Task 4: Modify app.py — Switch Endpoints to v2

**Files:**
- Modify: `mbr/app.py` (lines 525-581)

- [ ] **Step 1: Update /api/cert/templates to return variants from config**

In `mbr/app.py`, replace the `api_cert_templates` function (lines 525-533):

```python
# OLD:
@app.route("/api/cert/templates")
@login_required
def api_cert_templates():
    produkt = request.args.get("produkt", "")
    if not produkt:
        return jsonify({"templates": []})
    from mbr.cert_gen import list_templates_for_product
    templates = list_templates_for_product(produkt)
    return jsonify({"templates": templates})
```

Replace with:

```python
@app.route("/api/cert/templates")
@login_required
def api_cert_templates():
    produkt = request.args.get("produkt", "")
    if not produkt:
        return jsonify({"templates": []})
    from mbr.cert_gen_v2 import get_variants, get_required_fields
    variants = get_variants(produkt)
    templates = []
    for v in variants:
        templates.append({
            "filename": v["id"],
            "display": v["label"],
            "flags": v["flags"],
            "required_fields": get_required_fields(produkt, v["id"]),
        })
    return jsonify({"templates": templates})
```

- [ ] **Step 2: Update /api/cert/generate to use cert_gen_v2**

In `mbr/app.py`, replace the `api_cert_generate` function (lines 536-581):

```python
# OLD:
@app.route("/api/cert/generate", methods=["POST"])
@login_required
def api_cert_generate():
    data = request.get_json(silent=True)
    ebr_id = data.get("ebr_id")
    template_name = data.get("template_name")
    # ... old cert_gen logic
```

Replace with:

```python
@app.route("/api/cert/generate", methods=["POST"])
@login_required
def api_cert_generate():
    data = request.get_json(silent=True) or {}
    ebr_id = data.get("ebr_id")
    variant_id = data.get("variant_id") or data.get("template_name")
    extra_fields = data.get("extra_fields", {})

    if not ebr_id or not variant_id:
        return jsonify({"ok": False, "error": "Missing ebr_id or variant_id"}), 400

    from mbr.cert_gen_v2 import generate_certificate_pdf, save_certificate_pdf, load_config, get_variants

    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if not ebr:
            return jsonify({"ok": False, "error": "EBR not found"}), 404

        wyniki = get_ebr_wyniki(db, ebr_id)
        # Flatten wyniki: latest value per kod across all sekcjas
        wyniki_flat = {}
        for sekcja_data in wyniki.values():
            for kod, row in sekcja_data.items():
                wyniki_flat[kod] = row

        # Resolve wystawil
        shift_ids = session.get("shift_workers", [])
        if shift_ids:
            workers = []
            for wid in shift_ids:
                w = db.execute("SELECT nickname FROM workers WHERE id=?", (wid,)).fetchone()
                if w:
                    workers.append(w["nickname"])
            wystawil = ", ".join(workers) if workers else session["user"]["login"]
        else:
            wystawil = session["user"]["login"]

        # Find variant label for filename
        variants = get_variants(ebr["produkt"])
        variant_label = variant_id
        for v in variants:
            if v["id"] == variant_id:
                variant_label = v["label"]
                break

        try:
            pdf_bytes = generate_certificate_pdf(
                ebr["produkt"], variant_id, ebr["nr_partii"],
                ebr.get("dt_start"), wyniki_flat, extra_fields,
            )
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

        pdf_path = save_certificate_pdf(pdf_bytes, ebr["produkt"], variant_label, ebr["nr_partii"])
        cert_id = create_swiadectwo(db, ebr_id, variant_label, ebr["nr_partii"], pdf_path, wystawil)

    return jsonify({"ok": True, "cert_id": cert_id, "pdf_path": pdf_path})
```

- [ ] **Step 3: Verify endpoints work**

Start the Flask app and test with curl:
```bash
# Test templates endpoint
curl -s "http://localhost:5000/api/cert/templates?produkt=Chegina_K40GLOL" | python3 -m json.tool | head -20
```

Expected: JSON with `templates` array containing variant objects with `filename`, `display`, `flags`, `required_fields`.

- [ ] **Step 4: Commit**

```bash
git add mbr/app.py
git commit -m "feat: switch certificate endpoints to cert_gen_v2 config-driven system"
```

---

### Task 5: Update UI — Popup for Required Fields

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html` (lines 798-864)

- [ ] **Step 1: Add popup HTML + CSS for extra fields**

In `_fast_entry_content.html`, add this CSS block inside the existing `<style>` tag (after the `.cv-row-btn-issue` styles, around line 433):

```css
/* Certificate extra fields popup */
.cv-popup-overlay {
  display: none;
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.35);
  z-index: 9000;
  align-items: center;
  justify-content: center;
}
.cv-popup-overlay.active { display: flex; }
.cv-popup {
  background: #fff;
  border-radius: 12px;
  padding: 24px;
  min-width: 340px;
  max-width: 440px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.18);
}
.cv-popup h3 {
  margin: 0 0 16px 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
}
.cv-popup-field {
  margin-bottom: 12px;
}
.cv-popup-field label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-sec);
  margin-bottom: 4px;
}
.cv-popup-field input {
  width: 100%;
  padding: 8px 10px;
  border: 1.5px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
  box-sizing: border-box;
}
.cv-popup-field input:focus {
  border-color: var(--teal);
  outline: none;
}
.cv-popup-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 16px;
}
.cv-popup-btn {
  padding: 8px 18px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border: 1.5px solid var(--border);
  background: #fff;
  color: var(--text);
}
.cv-popup-btn:hover { background: var(--surface-alt); }
.cv-popup-btn-ok {
  background: var(--teal);
  color: #fff;
  border-color: var(--teal);
}
.cv-popup-btn-ok:hover { opacity: 0.9; }
```

Add this HTML just before the closing `</div>` of the main content area (before the final `<script>` block):

```html
<!-- Certificate extra fields popup -->
<div class="cv-popup-overlay" id="cv-popup-overlay">
  <div class="cv-popup">
    <h3 id="cv-popup-title">Dodatkowe dane świadectwa</h3>
    <div id="cv-popup-fields"></div>
    <div class="cv-popup-actions">
      <button class="cv-popup-btn" onclick="closeCertPopup()">Anuluj</button>
      <button class="cv-popup-btn cv-popup-btn-ok" onclick="confirmCertPopup()">Wystaw</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Update template list rendering to pass flags**

In `_fast_entry_content.html`, update the template row rendering inside `loadCompletedCerts()` (around line 800-805). Replace:

```javascript
        tmplData.templates.forEach(function(t) {
            html += '<div class="cv-row cv-row-tmpl">' +
                '<div class="cv-row-dot tmpl"></div>' +
                '<span class="cv-row-name">' + t.display + '</span>' +
                '<button class="cv-row-btn-issue" onclick="generateCertInline(this,\'' + t.filename.replace(/'/g, "\\'") + '\')">+ Wystaw</button>' +
            '</div>';
        });
```

With:

```javascript
        tmplData.templates.forEach(function(t) {
            var reqJson = JSON.stringify(t.required_fields || []).replace(/'/g, "\\'").replace(/"/g, '&quot;');
            html += '<div class="cv-row cv-row-tmpl">' +
                '<div class="cv-row-dot tmpl"></div>' +
                '<span class="cv-row-name">' + t.display + '</span>' +
                '<button class="cv-row-btn-issue" onclick="issueCert(this,\'' + t.filename.replace(/'/g, "\\'") + '\',' + JSON.stringify(t.required_fields || []) + ')">+ Wystaw</button>' +
            '</div>';
        });
```

- [ ] **Step 3: Replace generateCertInline with issueCert + popup logic**

In `_fast_entry_content.html`, replace the `generateCertInline` function (lines 845-864) with:

```javascript
var _pendingCert = {btn: null, variantId: null, requiredFields: []};

function issueCert(btn, variantId, requiredFields) {
    if (!requiredFields || requiredFields.length === 0) {
        // No extra fields needed — generate directly
        doGenerateCert(btn, variantId, {});
        return;
    }
    // Show popup for required fields
    _pendingCert = {btn: btn, variantId: variantId, requiredFields: requiredFields};
    var fieldsHtml = '';
    var fieldDefs = {
        'has_order_number': {label: 'Numer zamówienia / Order No.', key: 'order_number'},
        'has_certificate_number': {label: 'Numer certyfikatu / Certificate No.', key: 'certificate_number'},
        'has_avon_code': {label: 'Kod AVON / AVON code', key: 'avon_code'},
        'has_avon_name': {label: 'Nazwa AVON / AVON name (INCI)', key: 'avon_name'},
    };
    requiredFields.forEach(function(flag) {
        var def = fieldDefs[flag];
        if (def) {
            fieldsHtml += '<div class="cv-popup-field">' +
                '<label>' + def.label + '</label>' +
                '<input type="text" id="cv-field-' + def.key + '" data-key="' + def.key + '" required>' +
                '</div>';
        }
    });
    document.getElementById('cv-popup-fields').innerHTML = fieldsHtml;
    document.getElementById('cv-popup-overlay').classList.add('active');
    // Focus first input
    var first = document.querySelector('#cv-popup-fields input');
    if (first) setTimeout(function() { first.focus(); }, 100);
}

function closeCertPopup() {
    document.getElementById('cv-popup-overlay').classList.remove('active');
    _pendingCert = {btn: null, variantId: null, requiredFields: []};
}

function confirmCertPopup() {
    var extra = {};
    var inputs = document.querySelectorAll('#cv-popup-fields input');
    var valid = true;
    inputs.forEach(function(inp) {
        var val = inp.value.trim();
        if (!val) {
            inp.style.borderColor = '#ef4444';
            valid = false;
        } else {
            inp.style.borderColor = '';
        }
        extra[inp.dataset.key] = val;
    });
    if (!valid) return;
    closeCertPopup();
    doGenerateCert(_pendingCert.btn, _pendingCert.variantId, extra);
}

async function doGenerateCert(btn, variantId, extraFields) {
    btn.disabled = true;
    btn.style.opacity = '0.5';
    var origText = btn.innerHTML;
    btn.innerHTML = '<span>Generowanie...</span>';
    var resp = await fetch('/api/cert/generate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            ebr_id: ebrId,
            variant_id: variantId,
            extra_fields: extraFields
        })
    });
    var data = await resp.json();
    if (data.ok) {
        window.open('/api/cert/' + data.cert_id + '/pdf', '_blank');
        loadCompletedCerts();
    } else {
        btn.disabled = false;
        btn.style.opacity = '1';
        btn.innerHTML = origText;
        alert('Błąd: ' + (data.error || 'Nieznany błąd'));
    }
}
```

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: add popup for required certificate fields (order no, cert no, AVON)"
```

---

### Task 6: Update seed_mbr.py — Add Missing Parameters

**Files:**
- Modify: `mbr/seed_mbr.py`

- [ ] **Step 1: Add barwa_hz to products that are missing it**

In `mbr/seed_mbr.py`, add `_bezp("barwa_hz", "Barwa Hz", "barwa_hz", 0, 500, 0)` to the `"analiza"` (or `"analiza_koncowa"`) section of these products. Add it right after the existing `barwa_fau` field in each product.

Products to update (find each product's `parametry_lab` dict and add `barwa_hz` after `barwa_fau`):
- `Chegina_K40GLOL` — if missing
- `Chegina_K40GLOS`
- `Chegina_K40GLN`
- `Chegina_GLOL40`
- `Chegina_K7B`
- `Chegina_KK`
- `Chegina_CC`
- `Chegina_CCR`
- `Cheminox_K`
- `Cheminox_K35`

For each, add this line after the `barwa_fau` line:
```python
_bezp("barwa_hz",    "Barwa Hz",    "barwa_hz",   0,     500,   0),
```

- [ ] **Step 2: Add wolna_amina to products that need it**

Add `_titr("wolna_amina", "%wolna amina", "wolna_amina", 0, 0.5, 2)` to:
- `Chegina_KK` — after `aa` field
- `Chegina_K40GLN` — after `aa` field (if missing)
- `Chegina_K40GLOS` — after `aa` field (if missing)
- `Chegina_GLOL40` — after `sa` field

- [ ] **Step 3: Add other missing per-product parameters**

For `Chegina_K40GLO`: add `_bezp("gestosc", "Gęstość", "gestosc", 1.05, 1.09, 2)` if missing.

For `Chegina_KK`: add these if missing:
```python
_bezp("mca",    "MCA [ppm]",   "mca",    0,   3000,  0),
_bezp("dca",    "DCA [ppm]",   "dca",    0,   400,   0),
_bezp("dmapa",  "DMAPA [ppm]", "dmapa",  0,   100,   0),
```

- [ ] **Step 4: Verify seed_mbr loads without syntax errors**

Run:
```bash
cd /Users/tbk/Desktop/aa && python3 -c "from mbr.seed_mbr import PRODUCTS; print(f'OK: {len(PRODUCTS)} products')"
```

Expected: `OK: NN products` (no errors)

- [ ] **Step 5: Commit**

```bash
git add mbr/seed_mbr.py
git commit -m "feat: add missing analysis parameters for certificate generation

Add barwa_hz to 10 products, wolna_amina to 4 products,
gestosc to K40GLO, MCA/DCA/DMAPA to KK."
```

---

### Task 7: Integration Test — End-to-End Certificate Generation

**Files:**
- No files created — manual verification

- [ ] **Step 1: Start the app and test full flow**

```bash
cd /Users/tbk/Desktop/aa && python3 -m mbr.app
```

In a separate terminal:

```bash
# 1. Get templates for a product
curl -s "http://localhost:5000/api/cert/templates?produkt=Chegina_K40GLOL" | python3 -m json.tool

# 2. Should return variants with flags and required_fields
```

Expected: JSON with `templates` array, each item has `filename` (variant id), `display`, `flags`, `required_fields`.

- [ ] **Step 2: Generate a test certificate for a completed EBR**

Find a completed EBR:
```bash
sqlite3 data/batch_db_v4.sqlite "SELECT ebr_id, produkt, nr_partii, status FROM ebr_batches WHERE status='completed' AND typ='zbiornik' LIMIT 5;"
```

Generate using one of the results:
```bash
curl -s -X POST "http://localhost:5000/api/cert/generate" \
  -H "Content-Type: application/json" \
  -d '{"ebr_id": <EBR_ID>, "variant_id": "base"}' | python3 -m json.tool
```

Expected: `{"ok": true, "cert_id": N, "pdf_path": "data/swiadectwa/...pdf"}`

- [ ] **Step 3: Test variant with required fields**

```bash
curl -s -X POST "http://localhost:5000/api/cert/generate" \
  -H "Content-Type: application/json" \
  -d '{"ebr_id": <EBR_ID>, "variant_id": "loreal_belgia", "extra_fields": {"order_number": "PO-12345", "certificate_number": "CERT-2026-001"}}' | python3 -m json.tool
```

Expected: `{"ok": true, ...}`. Open the PDF and verify order number and certificate number appear.

- [ ] **Step 4: Visual comparison**

Open the generated PDF and compare side-by-side with an original .docx certificate (open one from `data/wzory/`). Verify:
- Same general layout (header, meta table, results table, opinion, footer)
- Polish/English bilingual text present
- Parameter values formatted with Polish comma notation
- Qualitative fields show "zgodny /right"
- Dates formatted as DD.MM.YYYY

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: complete certificate master template system v2

Replaces .docx template parsing with JSON config + HTML master.
- cert_config.json: 31 products, ~86 variants
- cert_gen_v2.py: config-driven generation engine
- cert_master.html: single Jinja2 template
- UI popup for required fields (order no, cert no, AVON)
- Missing analysis parameters added to seed_mbr.py"
```
