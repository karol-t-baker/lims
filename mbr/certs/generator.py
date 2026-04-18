"""Config-driven certificate PDF generation (v2).

Replaces the old docx-parsing system (cert_gen.py) with a config-driven approach
using cert_config.json for product/variant definitions.

Rendering: docxtpl fills .docx master template → Gotenberg converts to PDF.
"""
import copy
import io
import json
import re
from datetime import date, datetime
from pathlib import Path

import requests
from docxtpl import DocxTemplate, RichText


# Lightweight markup for parameter names: `^{...}` → superscript, `_{...}` → subscript.
# Example: "n_{D}^{20}" renders as n with D subscript and 20 superscript.
# Chosen over bare `^foo^`/`_foo_` because underscores and carets are common in chemical
# identifiers and product names — the explicit `{...}` braces prevent accidental matches.
_RT_RE = re.compile(r"(\^\{[^}]*\}|_\{[^}]*\})")


_CERT_FONT = "TeX Gyre Bonum"
_CERT_SIZE = 22  # 11pt in half-points (docxtpl w:sz unit)


def _md_to_richtext(text: str, *, font: str = None, size: int = None) -> RichText:
    """Convert a string with `^{sup}` / `_{sub}` / `|` markers into a docxtpl RichText.

    Markers:
      - `^{X}` — superscript
      - `_{X}` — subscript
      - `|`  — manual line break (renders as <w:br/>)

    Plain strings (no markers) are still returned as RichText — the template uses
    `{{r ... }}` tags everywhere, so values must be RichText objects.
    Font and size set explicitly because {{r}} replaces the entire run,
    losing the template's formatting.

    Args:
        text: Markup string with optional ^{...}/_{...}/| markers.
        font: Font family override. Defaults to module constant _CERT_FONT.
        size: Font size in half-points. Defaults to module constant _CERT_SIZE.
    """
    font = font or _CERT_FONT
    size = size or _CERT_SIZE
    rt = RichText()
    if not text:
        return rt
    # Split on '|' first — each segment is rendered with its sub/sup markers,
    # and we inject <w:br/> between segments via direct XML manipulation.
    segments = text.split("|")
    for seg_idx, seg in enumerate(segments):
        for part in _RT_RE.split(seg):
            if not part:
                continue
            if part.startswith("^{") and part.endswith("}"):
                rt.add(part[2:-1], superscript=True, font=font, size=size)
            elif part.startswith("_{") and part.endswith("}"):
                rt.add(part[2:-1], subscript=True, font=font, size=size)
            else:
                rt.add(part, font=font, size=size)
        if seg_idx < len(segments) - 1:
            # Insert a line break element directly into the XML.
            # RichText.xml is a simple string concatenation of run elements,
            # so we inject <w:br/> as a sibling run element.
            rt.xml += "<w:br/>"
    return rt


def _load_cert_settings(db) -> dict:
    """Load typography settings from cert_settings table.

    Returns dict with typed values:
      - body_font_family: str
      - header_font_size_pt: int

    Missing keys fall back to defaults (same as seed in init_mbr_tables).
    """
    defaults = {"body_font_family": "TeX Gyre Bonum", "header_font_size_pt": 14}
    rows = db.execute("SELECT key, value FROM cert_settings").fetchall()
    out = dict(defaults)
    for r in rows:
        k = r["key"]
        v = r["value"]
        if k == "header_font_size_pt":
            try:
                out[k] = int(v)
            except (ValueError, TypeError):
                out[k] = defaults[k]
        else:
            out[k] = v
    return out


_CONFIG_PATH = Path(__file__).resolve().parent.parent / "cert_config.json"
_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "cert_master_template.docx"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # Desktop/aa/
OUTPUT_DIR = _PROJECT_ROOT / "data" / "swiadectwa"

GOTENBERG_URL = "http://localhost:3000"

_cached_config: dict | None = None


# ---------------------------------------------------------------------------
# 1. load_config
# ---------------------------------------------------------------------------
def load_config(*, reload: bool = False) -> dict:
    """Load cert_config.json from same directory as this module. Cache after first load."""
    global _cached_config
    if _cached_config is not None and not reload:
        return _cached_config
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        _cached_config = json.load(f)
    return _cached_config


# ---------------------------------------------------------------------------
# 2. get_variants
# ---------------------------------------------------------------------------
def get_variants(produkt: str) -> list[dict]:
    """Return list of {id, label, flags} for a product from DB."""
    from mbr.db import db_session as _db_session
    key = produkt if "_" in produkt else produkt.replace(" ", "_")
    try:
        with _db_session() as db:
            rows = db.execute(
                "SELECT variant_id, label, flags FROM cert_variants "
                "WHERE produkt=? ORDER BY kolejnosc", (key,)
            ).fetchall()
            if not rows:
                rows = db.execute(
                    "SELECT variant_id, label, flags FROM cert_variants "
                    "WHERE produkt=? ORDER BY kolejnosc",
                    (produkt.replace(" ", "_"),)
                ).fetchall()
            return [{"id": r["variant_id"], "label": r["label"],
                     "flags": json.loads(r["flags"] or "[]")} for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 3. get_required_fields
# ---------------------------------------------------------------------------
def get_required_fields(produkt: str, variant_id: str) -> list[str]:
    """Return flags that need user input for a variant from DB."""
    from mbr.db import db_session as _db_session
    key = produkt if "_" in produkt else produkt.replace(" ", "_")
    try:
        with _db_session() as db:
            row = db.execute(
                "SELECT flags, avon_code, avon_name FROM cert_variants "
                "WHERE produkt=? AND variant_id=?", (key, variant_id)
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


# ---------------------------------------------------------------------------
# 4. _format_value
# ---------------------------------------------------------------------------
def _format_value(value: float, fmt: str) -> str:
    """Format numeric value with Polish decimal comma.

    Args:
        value: Numeric value to format.
        fmt: Number of decimal places as string ("0", "1", "2", "3").
    """
    places = int(fmt)
    formatted = f"{value:.{places}f}"
    return formatted.replace(".", ",")


# ---------------------------------------------------------------------------
# 5. build_context
# ---------------------------------------------------------------------------
def build_context(
    produkt: str,
    variant_id: str,
    nr_partii: str,
    dt_start,
    wyniki_flat: dict,
    extra_fields: dict | None = None,
    wystawil: str = "",
) -> dict:
    """Build Jinja2 context dict for certificate rendering (DB-only).

    Args:
        produkt: Product key (e.g. "Chegina_K40GLOL").
        variant_id: Variant id (e.g. "base", "loreal").
        nr_partii: Batch number string.
        dt_start: Production start date (date, datetime, or ISO string).
        wyniki_flat: Lab results dict {kod: value_or_dict}.
        extra_fields: Optional dict with user-entered fields (order_number, etc.).
        wystawil: Name of person issuing the certificate.

    Returns:
        Context dict ready for template rendering.
    """
    cfg = load_config()
    from mbr.db import db_session as _db_session

    key = produkt if "_" in produkt else produkt.replace(" ", "_")

    with _db_session() as db:
        _settings = _load_cert_settings(db)

        # 1. Product metadata from produkty
        prod_row = db.execute(
            "SELECT display_name, spec_number, cas_number, expiry_months, "
            "opinion_pl, opinion_en FROM produkty WHERE nazwa = ?",
            (key,),
        ).fetchone()
        if prod_row is None:
            raise ValueError(f"Unknown product: {produkt}")

        _display_name = prod_row["display_name"] or key
        _spec_number = prod_row["spec_number"] or ""
        _cas_number = prod_row["cas_number"] or ""
        _expiry_months = prod_row["expiry_months"] or 12
        _opinion_pl = prod_row["opinion_pl"] or ""
        _opinion_en = prod_row["opinion_en"] or ""

        # 2. Variant data from cert_variants
        var_row = db.execute(
            "SELECT * FROM cert_variants WHERE produkt=? AND variant_id=?",
            (key, variant_id),
        ).fetchone()
        if var_row is None:
            raise ValueError(f"Unknown variant '{variant_id}' for product '{produkt}'")

        flags = json.loads(var_row["flags"] or "[]")
        remove_params = set(json.loads(var_row["remove_params"] or "[]"))

        # Apply variant overrides on top of product values
        spec_number = var_row["spec_number"] or _spec_number
        opinion_pl = var_row["opinion_pl"] or _opinion_pl
        opinion_en = var_row["opinion_en"] or _opinion_en

        # 3. Base parameter rows — prefer parametry_etapy, fallback to parametry_cert
        from mbr.parametry.registry import get_cert_params, get_cert_variant_params

        etapy_params = get_cert_params(db, key)
        if etapy_params:
            base_param_rows = etapy_params
        else:
            _legacy = db.execute(
                "SELECT pc.*, pa.kod, pa.label AS pa_label, pa.name_en AS pa_name_en, "
                "pa.method_code AS pa_method_code "
                "FROM parametry_cert pc "
                "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
                "WHERE pc.produkt = ? AND pc.variant_id IS NULL "
                "ORDER BY pc.kolejnosc",
                (key,),
            ).fetchall()
            base_param_rows = [
                {
                    "kod": r["kod"],
                    "parametr_id": r["parametr_id"],
                    "name_pl": r["name_pl"] or r["pa_label"] or "",
                    "name_en": r["name_en"] if r["name_en"] is not None else (r["pa_name_en"] or ""),
                    "method": r["method"] or r["pa_method_code"] or "",
                    "requirement": r["requirement"] or "",
                    "format": r["format"] or "1",
                    "qualitative_result": r["qualitative_result"],
                }
                for r in _legacy
            ]

        # 4. Filter out remove_params
        if remove_params:
            base_param_rows = [r for r in base_param_rows if r["parametr_id"] not in remove_params]

        # 5. Variant-specific params
        etapy_variant = get_cert_variant_params(db, var_row["id"])
        if etapy_variant:
            variant_param_rows = etapy_variant
        else:
            _legacy_v = db.execute(
                "SELECT pc.*, pa.kod, pa.label AS pa_label, pa.name_en AS pa_name_en, "
                "pa.method_code AS pa_method_code "
                "FROM parametry_cert pc "
                "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
                "WHERE pc.variant_id = ? ORDER BY pc.kolejnosc",
                (var_row["id"],),
            ).fetchall()
            variant_param_rows = [
                {
                    "kod": r["kod"],
                    "parametr_id": r["parametr_id"],
                    "name_pl": r["name_pl"] or r["pa_label"] or "",
                    "name_en": r["name_en"] if r["name_en"] is not None else (r["pa_name_en"] or ""),
                    "method": r["method"] or r["pa_method_code"] or "",
                    "requirement": r["requirement"] or "",
                    "format": r["format"] or "1",
                    "qualitative_result": r["qualitative_result"],
                }
                for r in _legacy_v
            ]

        all_param_rows = base_param_rows + variant_param_rows

        # 6. Build template rows
        rows = []
        for r in all_param_rows:
            name_pl = r["name_pl"]
            name_en = r["name_en"]
            method = r["method"]

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
                        result = _format_value(float(val), r["format"])
                    except (ValueError, TypeError):
                        result = str(val).replace(".", ",")

            rows.append({
                "name_pl": _md_to_richtext(name_pl, font=_settings["body_font_family"]),
                "name_en": _md_to_richtext(f"/{name_en}", font=_settings["body_font_family"]) if name_en else None,
                "requirement": r["requirement"],
                "method": method,
                "result": result,
            })

    # Calculate dates
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
            expiry_months = _expiry_months
            # Add expiry_months
            year = dt_obj.year + (dt_obj.month - 1 + expiry_months) // 12
            month = (dt_obj.month - 1 + expiry_months) % 12 + 1
            day = min(dt_obj.day, _days_in_month(year, month))
            dt_waznosci = date(year, month, day).strftime("%d.%m.%Y")

    # Optional fields from flags + extra_fields
    extra = extra_fields or {}
    flags_set = set(flags)

    order_number = extra.get("order_number", "") if "has_order_number" in flags_set else ""
    certificate_number = extra.get("certificate_number", "") if "has_certificate_number" in flags_set else ""
    has_rspo = "has_rspo" in flags_set
    rspo_number = cfg.get("rspo_number", "CU-RSPO SCC-857488")
    rspo_text = rspo_number if has_rspo else ""
    # If MB variant (has_rspo but no has_certificate_number), auto-fill certificate_number with RSPO
    if has_rspo and "has_certificate_number" not in flags_set:
        certificate_number = rspo_text
        rspo_text = ""
    # Avon fields: prefer static values from variant, fallback to user input
    avon_code = var_row["avon_code"] or extra.get("avon_code", "") if "has_avon_code" in flags_set else ""
    avon_name = var_row["avon_name"] or extra.get("avon_name", "") if "has_avon_name" in flags_set else ""

    return {
        "company": cfg["company"],
        "footer": cfg["footer"],
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
        "body_font_family": _settings["body_font_family"],
        "header_font_size_pt": _settings["header_font_size_pt"],
    }


def build_preview_context(product_json: dict, variant_id: str) -> dict:
    """Build template context directly from editor JSON payload (no DB).

    Used for live PDF preview while editing cert config.

    Args:
        product_json: Full product object from the editor UI.
        variant_id: Which variant to preview.

    Returns:
        Context dict matching the structure of build_context().
    """
    cfg = load_config()

    # Typography settings from cert_settings table
    from mbr.db import db_session as _db_session
    with _db_session() as _db:
        _settings = _load_cert_settings(_db)

    # 1. Global settings from cert_config.json
    company = cfg.get("company", {})
    footer = cfg.get("footer", {})
    rspo_number = cfg.get("rspo_number", "CU-RSPO SCC-857488")

    # 2. Product meta from product_json
    display_name = product_json.get("display_name", "Produkt")
    spec_number = product_json.get("spec_number", "")
    cas_number = product_json.get("cas_number", "")
    expiry_months = product_json.get("expiry_months", 12)
    opinion_pl = product_json.get("opinion_pl", "")
    opinion_en = product_json.get("opinion_en", "")

    # 3. Find requested variant
    variant = None
    for v in product_json.get("variants", []):
        if v["id"] == variant_id:
            variant = v
            break
    if variant is None:
        # Fallback to first variant
        variants_list = product_json.get("variants", [])
        variant = variants_list[0] if variants_list else {
            "id": "base", "label": display_name, "flags": [], "overrides": {}
        }

    # 4. Apply variant overrides
    overrides = variant.get("overrides", {})
    spec_number = overrides.get("spec_number") or spec_number
    opinion_pl = overrides.get("opinion_pl") or opinion_pl
    opinion_en = overrides.get("opinion_en") or opinion_en

    # 5. Apply remove_parameters and add_parameters
    parameters = copy.deepcopy(product_json.get("parameters", []))
    remove_ids = set(overrides.get("remove_parameters", []))
    if remove_ids:
        parameters = [p for p in parameters if p["id"] not in remove_ids]
    add_params = overrides.get("add_parameters", [])
    if add_params:
        parameters.extend(copy.deepcopy(add_params))

    # 6. Build rows with test data
    rows = []
    for param in parameters:
        result = ""
        if param.get("qualitative_result"):
            result = param["qualitative_result"]
        elif param.get("data_field"):
            fmt = param.get("format") or "1"
            result = _format_value(12.34, fmt)
        _ne = param.get("name_en", "")
        rows.append({
            "name_pl": _md_to_richtext(param.get("name_pl", ""), font=_settings["body_font_family"]),
            "name_en": _md_to_richtext(f"/{_ne}", font=_settings["body_font_family"]) if _ne else None,
            "requirement": param.get("requirement", ""),
            "method": param.get("method", ""),
            "result": result,
        })

    # 7. Generate test dates
    today = date.today()
    dt_produkcji = today.strftime("%d.%m.%Y")
    year = today.year + (today.month - 1 + expiry_months) // 12
    month = (today.month - 1 + expiry_months) % 12 + 1
    day = min(today.day, _days_in_month(year, month))
    dt_waznosci = date(year, month, day).strftime("%d.%m.%Y")
    dt_wystawienia = dt_produkcji

    # 8. Handle flags
    flags = set(variant.get("flags", []))
    has_rspo = "has_rspo" in flags
    rspo_text = rspo_number if has_rspo else ""
    order_number = "TEST-ORDER-001" if "has_order_number" in flags else ""
    certificate_number = ""
    if "has_certificate_number" in flags:
        certificate_number = "CERT-001"
    if has_rspo and "has_certificate_number" not in flags:
        certificate_number = rspo_text
        rspo_text = ""
    avon_code = overrides.get("avon_code") or ("AVON-CODE" if "has_avon_code" in flags else "")
    avon_name = overrides.get("avon_name") or ("Avon Product Name" if "has_avon_name" in flags else "")

    # 9. Return context
    return {
        "company": company,
        "footer": footer,
        "display_name": display_name + (" MB" if has_rspo else ""),
        "spec_number": spec_number,
        "cas_number": cas_number,
        "nr_partii": "1/2026",
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
        "wystawil": "Podgląd",
        "body_font_family": _settings["body_font_family"],
        "header_font_size_pt": _settings["header_font_size_pt"],
    }


def export_cert_config(db) -> dict:
    """Build the full cert_config.json structure from DB tables.

    Reads company/footer/rspo from the existing JSON file.
    Products, parameters, and variants come from DB.

    Args:
        db: Active database connection (sqlite3.Connection with row_factory).

    Returns:
        Dict matching the cert_config.json structure.
    """
    cfg = load_config()
    result = {
        "company": cfg.get("company", {}),
        "footer": cfg.get("footer", {}),
        "rspo_number": cfg.get("rspo_number", "CU-RSPO SCC-857488"),
        "products": {},
    }

    # Get all products that have cert data
    produkty = db.execute(
        "SELECT DISTINCT p.nazwa, p.display_name, p.spec_number, p.cas_number, "
        "p.expiry_months, p.opinion_pl, p.opinion_en "
        "FROM produkty p "
        "WHERE EXISTS (SELECT 1 FROM cert_variants cv WHERE cv.produkt = p.nazwa) "
        "ORDER BY p.nazwa"
    ).fetchall()

    # One-shot id → kod map — avoids the per-removed-param SELECT below.
    _id_to_kod = {
        r["id"]: r["kod"] for r in db.execute(
            "SELECT id, kod FROM parametry_analityczne"
        ).fetchall()
    }

    for prod in produkty:
        key = prod["nazwa"]

        # Product metadata
        product_obj = {
            "display_name": prod["display_name"] or key,
            "spec_number": prod["spec_number"] or "",
            "cas_number": prod["cas_number"] or "",
            "expiry_months": prod["expiry_months"] or 12,
            "opinion_pl": prod["opinion_pl"] or "",
            "opinion_en": prod["opinion_en"] or "",
        }

        # Base parameters (variant_id IS NULL)
        base_params = db.execute(
            "SELECT pc.parametr_id, pc.kolejnosc, pc.requirement, pc.format, "
            "pc.qualitative_result, pc.name_pl, pc.name_en, pc.method, "
            "pa.kod, pa.label AS pa_label, pa.name_en AS pa_name_en, "
            "pa.method_code AS pa_method_code "
            "FROM parametry_cert pc "
            "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
            "WHERE pc.produkt = ? AND pc.variant_id IS NULL "
            "ORDER BY pc.kolejnosc",
            (key,),
        ).fetchall()

        parameters = []
        for bp in base_params:
            param = {
                "id": bp["kod"] or f"param_{bp['parametr_id']}",
                "name_pl": bp["name_pl"] or bp["pa_label"] or "",
                "name_en": bp["name_en"] or bp["pa_name_en"] or "",
                "requirement": bp["requirement"] or "",
                "method": bp["method"] or bp["pa_method_code"] or "",
                "format": bp["format"] or "1",
                "data_field": bp["kod"] or "",
            }
            if bp["qualitative_result"]:
                param["qualitative_result"] = bp["qualitative_result"]
            parameters.append(param)
        product_obj["parameters"] = parameters

        # Variants
        variants_db = db.execute(
            "SELECT * FROM cert_variants WHERE produkt=? ORDER BY kolejnosc",
            (key,),
        ).fetchall()

        variants = []
        for vr in variants_db:
            variant_obj = {
                "id": vr["variant_id"],
                "label": vr["label"],
                "flags": json.loads(vr["flags"] or "[]"),
            }
            overrides = {}
            if vr["spec_number"]:
                overrides["spec_number"] = vr["spec_number"]
            if vr["opinion_pl"]:
                overrides["opinion_pl"] = vr["opinion_pl"]
            if vr["opinion_en"]:
                overrides["opinion_en"] = vr["opinion_en"]
            if vr["avon_code"]:
                overrides["avon_code"] = vr["avon_code"]
            if vr["avon_name"]:
                overrides["avon_name"] = vr["avon_name"]

            remove_params = json.loads(vr["remove_params"] or "[]")
            if remove_params:
                overrides["remove_parameters"] = [
                    _id_to_kod.get(pid) or f"param_{pid}" for pid in remove_params
                ]

            # Variant-specific add_parameters
            add_params_db = db.execute(
                "SELECT pc.*, pa.kod, pa.label AS pa_label, pa.name_en AS pa_name_en, "
                "pa.method_code AS pa_method_code "
                "FROM parametry_cert pc "
                "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
                "WHERE pc.variant_id = ? "
                "ORDER BY pc.kolejnosc",
                (vr["id"],),
            ).fetchall()

            if add_params_db:
                add_parameters = []
                for ap in add_params_db:
                    param = {
                        "id": ap["kod"] or f"param_{ap['parametr_id']}",
                        "name_pl": ap["name_pl"] or ap["pa_label"] or "",
                        "name_en": ap["name_en"] or ap["pa_name_en"] or "",
                        "requirement": ap["requirement"] or "",
                        "method": ap["method"] or ap["pa_method_code"] or "",
                        "format": ap["format"] or "1",
                        "data_field": ap["kod"] or "",
                    }
                    if ap["qualitative_result"]:
                        param["qualitative_result"] = ap["qualitative_result"]
                    add_parameters.append(param)
                overrides["add_parameters"] = add_parameters

            if overrides:
                variant_obj["overrides"] = overrides
            variants.append(variant_obj)

        product_obj["variants"] = variants
        result["products"][key] = product_obj

    return result


def save_cert_config_export(db=None) -> None:
    """Export cert config from DB and write atomically to cert_config.json.

    Args:
        db: Optional active connection. If omitted, opens a fresh one so the
            caller can safely run this AFTER committing/closing their own
            transaction — avoids reading uncommitted / stale snapshots.
    """
    if db is None:
        from mbr.db import db_session as _db_session
        with _db_session() as _db:
            data = export_cert_config(_db)
    else:
        data = export_cert_config(db)
    tmp_path = _CONFIG_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(_CONFIG_PATH)
    # Invalidate cached config
    global _cached_config
    _cached_config = None


def _days_in_month(year: int, month: int) -> int:
    """Return number of days in a given month."""
    import calendar
    return calendar.monthrange(year, month)[1]


# ---------------------------------------------------------------------------
# 6. generate_certificate_pdf
# ---------------------------------------------------------------------------
def _escape_xml_chars(context: dict) -> dict:
    """Escape < and > in string values so docxtpl/XML doesn't eat them."""
    def _esc(val):
        if isinstance(val, str):
            return val.replace("<", "﹤").replace(">", "﹥")
        if isinstance(val, list):
            return [_esc(item) for item in val]
        if isinstance(val, dict):
            return {k: _esc(v) for k, v in val.items()}
        return val
    return _esc(context)


def _fix_single_line_valign(doc) -> None:
    """Fix vertical centering for single-paragraph cells in the params table.

    LibreOffice ignores vAlign=center when a cell has only 1 paragraph.
    Workaround: for cells without name_en (1 paragraph), add a tiny empty
    paragraph with minimal line spacing to match the 2-paragraph structure
    of cells with name_en, keeping visual height balanced.
    """
    from lxml import etree
    WNS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

    if not doc.tables:
        return
    table = doc.tables[0]
    for ri in range(1, len(table.rows)):
        cell = table.rows[ri].cells[0]
        paras = cell._element.findall(f'{{{WNS}}}p')
        if len(paras) != 1:
            continue
        # Clone paragraph properties from existing paragraph
        existing_pPr = paras[0].find(f'{{{WNS}}}pPr')
        # Create empty paragraph with small font
        new_p = etree.SubElement(cell._element, f'{{{WNS}}}p')
        new_pPr = etree.SubElement(new_p, f'{{{WNS}}}pPr')
        # Copy alignment (center)
        if existing_pPr is not None:
            jc = existing_pPr.find(f'{{{WNS}}}jc')
            if jc is not None:
                new_pPr.append(copy.deepcopy(jc))
        # Set small line spacing so empty paragraph takes minimal height
        sp = etree.SubElement(new_pPr, f'{{{WNS}}}spacing')
        sp.set(f'{{{WNS}}}line', '120')  # 6pt line spacing
        sp.set(f'{{{WNS}}}lineRule', 'exact')
        # Add empty run with same font but smaller size
        new_r = etree.SubElement(new_p, f'{{{WNS}}}r')
        new_rPr = etree.SubElement(new_r, f'{{{WNS}}}rPr')
        sz = etree.SubElement(new_rPr, f'{{{WNS}}}sz')
        sz.set(f'{{{WNS}}}val', '12')  # 6pt font
        new_t = etree.SubElement(new_r, f'{{{WNS}}}t')
        new_t.text = ' '


_SENTINEL_SZ = "999"
_BODY_FONT_LITERAL = "TeX Gyre Bonum"   # 298× in word/document.xml
_HEADER_FONT_LITERAL = "Bookman Old Style"  # 12× in word/header1.xml


def _docxtpl_render(context: dict) -> bytes:
    """Render the master .docx template with context, return .docx bytes.

    After docxtpl fills Jinja placeholders (which only work inside <w:t> text
    nodes), we post-process the raw DOCX bytes to apply typography settings
    that live in XML attributes — specifically font names in w:rFonts and font
    sizes in w:sz / w:szCs.  Those cannot be driven by docxtpl {{ }} tags.
    """
    tpl = DocxTemplate(str(_TEMPLATE_PATH))
    tpl.render(_escape_xml_chars(context))
    _fix_single_line_valign(tpl.docx)
    buf = io.BytesIO()
    tpl.save(buf)
    docx_bytes = buf.getvalue()
    font = context.get("body_font_family", _CERT_FONT)
    header_size_pt = context.get("header_font_size_pt", 14)
    return _apply_typography_overrides(docx_bytes, font, header_size_pt)


def _apply_typography_overrides(docx_bytes: bytes, font: str, header_size_pt: int) -> bytes:
    """Post-render byte-level substitution for typography settings.

    The template encodes two sentinels that cannot be handled by docxtpl:

    * word/document.xml  — body font: 298 occurrences of "TeX Gyre Bonum" in
      w:rFonts attributes.  Replaced globally with ``font``.

    * word/header1.xml   — header font: 12 occurrences of "Bookman Old Style".
      Replaced globally with ``font``.  Also contains sentinel
      ``<w:sz w:val="999"/>`` (1×) and ``<w:szCs w:val="999"/>`` (11×) which
      are replaced with ``header_size_pt * 2`` (half-points).

    * word/styles.xml    — Nagwek8 paragraph style carries
      ``<w:sz w:val="999"/>`` (1×).  Replaced with ``header_size_pt * 2``.

    The sentinel value 999 is chosen because it does not appear elsewhere in
    the template and is far outside any usable font size range.
    """
    import zipfile
    from io import BytesIO

    new_sz = str(int(header_size_pt) * 2)
    sentinel_sz = f'<w:sz w:val="{_SENTINEL_SZ}"/>'
    sentinel_szcs = f'<w:szCs w:val="{_SENTINEL_SZ}"/>'
    target_sz = f'<w:sz w:val="{new_sz}"/>'
    target_szcs = f'<w:szCs w:val="{new_sz}"/>'

    in_buf = BytesIO(docx_bytes)
    out_buf = BytesIO()
    with zipfile.ZipFile(in_buf, "r") as zin, \
         zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.namelist():
            data = zin.read(item)
            if item == "word/document.xml":
                txt = data.decode("utf-8")
                if font and font != _BODY_FONT_LITERAL:
                    txt = re.sub(
                        r'(w:ascii|w:hAnsi|w:cs|w:eastAsia)="' + re.escape(_BODY_FONT_LITERAL) + r'"',
                        lambda m: f'{m.group(1)}="{font}"',
                        txt,
                    )
                data = txt.encode("utf-8")
            elif item == "word/header1.xml":
                txt = data.decode("utf-8")
                if font and font != _HEADER_FONT_LITERAL:
                    txt = re.sub(
                        r'(w:ascii|w:hAnsi|w:cs|w:eastAsia)="' + re.escape(_HEADER_FONT_LITERAL) + r'"',
                        lambda m: f'{m.group(1)}="{font}"',
                        txt,
                    )
                txt = txt.replace(sentinel_sz, target_sz)
                txt = txt.replace(sentinel_szcs, target_szcs)
                data = txt.encode("utf-8")
            elif item == "word/styles.xml":
                txt = data.decode("utf-8")
                # styles.xml: only header size is parameterized here. The body font
                # is declared per-run in document.xml; styles.xml has no rFonts
                # referencing the body font literal. If a future refactor moves font
                # to styles.xml, add a font substitution pass to this block.
                txt = txt.replace(sentinel_sz, target_sz)
                data = txt.encode("utf-8")
            zout.writestr(item, data)
    return out_buf.getvalue()


def _gotenberg_convert(docx_bytes: bytes) -> bytes:
    """Send .docx to Gotenberg, return PDF bytes."""
    resp = requests.post(
        f"{GOTENBERG_URL}/forms/libreoffice/convert",
        files={"files": ("certificate.docx", docx_bytes,
                         "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content


def generate_certificate_pdf(
    produkt: str,
    variant_id: str,
    nr_partii: str,
    dt_start,
    wyniki_flat: dict,
    extra_fields: dict | None = None,
    wystawil: str = "",
) -> bytes:
    """Build context, render .docx via docxtpl, convert to PDF via Gotenberg.

    Returns:
        PDF file content as bytes.
    """
    ctx = build_context(produkt, variant_id, nr_partii, dt_start, wyniki_flat, extra_fields, wystawil=wystawil)
    docx_bytes = _docxtpl_render(ctx)
    return _gotenberg_convert(docx_bytes)


# ---------------------------------------------------------------------------
# 7. save_certificate_pdf
# ---------------------------------------------------------------------------
def _cert_names(produkt: str, variant_label: str, nr_partii: str) -> tuple[str, str, str]:
    """Derive product folder name, PDF filename, and batch number from inputs.

    variant_label examples: "Chegina K40GL", "Chegina K40GL — MB", "Chegina K7 — ADAM&PARTNER"
    nr_partii examples: "4/2026", "124/2026"

    Returns:
        (product_folder, pdf_name, nr_only)
        e.g. ("Chegina K40GL", "Chegina K40GL MB 4.pdf", "4")
    """
    # Product folder = produkt with spaces (e.g. "Chegina K40GL")
    product_folder = produkt.replace("_", " ")

    # Extract variant suffix (part after " — " dash)
    variant_suffix = ""
    if "\u2014" in variant_label:  # em dash
        variant_suffix = variant_label.split("\u2014", 1)[1].strip()
    elif " - " in variant_label:
        variant_suffix = variant_label.split(" - ", 1)[1].strip()

    # Nr only = number before slash (e.g. "4" from "4/2026")
    nr_only = nr_partii.split("/")[0].strip()

    # Build PDF name: "Chegina K40GL MB 4.pdf" or "Chegina K7 4.pdf" (no suffix for base)
    parts = [product_folder]
    if variant_suffix:
        parts.append(variant_suffix)
    parts.append(nr_only)
    pdf_name = " ".join(parts) + ".pdf"

    return product_folder, pdf_name, nr_only


def save_certificate_data(
    produkt: str,
    variant_label: str,
    nr_partii: str,
    generation_data: dict,
) -> str:
    """Save generation inputs as JSON to data/swiadectwa/ archive (for regeneration).

    Structure: data/swiadectwa/{year}/{product_folder}/{name}.json
    Returns: path relative to project root.
    """
    year = date.today().year
    product_folder, pdf_name, _ = _cert_names(produkt, variant_label, nr_partii)
    json_name = pdf_name.replace(".pdf", ".json")

    out_dir = OUTPUT_DIR / str(year) / product_folder
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / json_name

    import json
    json_path.write_text(json.dumps(generation_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(json_path.relative_to(_PROJECT_ROOT))


def save_certificate_pdf(
    pdf_bytes: bytes,
    produkt: str,
    variant_label: str,
    nr_partii: str,
    output_dir: str | None = None,
) -> str:
    """Save PDF to user-configured path.

    Structure: {output_dir}/{year}/{product_folder}/{pdf_name}
    Fallback: ~/Desktop/{year}/{product_folder}/{pdf_name}

    Returns: absolute path to saved PDF.
    """
    year = date.today().year
    product_folder, pdf_name, _ = _cert_names(produkt, variant_label, nr_partii)

    base_dir = Path(output_dir) if output_dir else Path.home() / "Desktop"
    target_dir = base_dir / str(year) / product_folder
    target_dir.mkdir(parents=True, exist_ok=True)

    full_path = target_dir / pdf_name
    full_path.write_bytes(pdf_bytes)

    return str(full_path)
