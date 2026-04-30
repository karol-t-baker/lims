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


_CERT_FONT = "Noto Serif"
_CERT_SIZE = 22  # 11pt in half-points (docxtpl w:sz unit)


def get_cert_aliases(db, source_produkt: str) -> list[str]:
    """Return list of target_produkt strings that source_produkt can alias into.

    An alias `(source_produkt, target_produkt)` means: batches of source_produkt
    can issue cert variants owned by target_produkt. Used by api_cert_templates
    to union variant lists and by api_cert_generate to validate the alias.
    """
    rows = db.execute(
        "SELECT target_produkt FROM cert_alias WHERE source_produkt = ? ORDER BY target_produkt",
        (source_produkt,),
    ).fetchall()
    return [r["target_produkt"] for r in rows]


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
            # Insert a line break run between segments. Per ECMA-376 CT_P,
            # <w:br/> must live inside a <w:r> — bare <w:br/> at paragraph
            # level is schema-invalid even though Word/LibreOffice tolerate
            # it. RichText.xml is a simple string concat of run elements,
            # so we append a self-contained break run.
            rt.xml += "<w:r><w:br/></w:r>"
    return rt


def _load_cert_settings(db) -> dict:
    """Load typography settings from cert_settings table.

    Returns dict with:
      - body_font_family: str
      - title_font_size_pt: int        — "ŚWIADECTWO / CERTIFICATE" heading
      - product_name_font_size_pt: int — {{display_name}}
      - body_font_size_pt: int         — table + body paragraphs
      - header_font_size_pt: int       — legacy, kept for backcompat only
    Missing rows fall back to hardcoded defaults.
    """
    defaults = {
        "body_font_family":          "Noto Serif",
        "header_font_family":        "Noto Sans",
        "header_font_size_pt":       14,   # legacy default
        "title_font_size_pt":        12,
        "product_name_font_size_pt": 16,
        "body_font_size_pt":         11,
    }
    int_keys = {
        "header_font_size_pt",
        "title_font_size_pt",
        "product_name_font_size_pt",
        "body_font_size_pt",
    }
    rows = db.execute("SELECT key, value FROM cert_settings").fetchall()
    out = dict(defaults)
    for r in rows:
        k = r["key"]
        v = r["value"]
        if k in int_keys:
            try:
                out[k] = int(v)
            except (ValueError, TypeError):
                out[k] = defaults.get(k, 11)
        elif k in defaults:
            out[k] = v
        # Unknown keys ignored — no need to surface them.
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
    """Return list of {id, label, flags, owner_produkt} for a product from DB.

    owner_produkt echoes back the produkt argument — used by callers that
    union variants across alias boundaries so the client knows which product
    owns each variant (for the generate-payload target_produkt field).
    """
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
                     "flags": json.loads(r["flags"] or "[]"),
                     "owner_produkt": key} for r in rows]
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
            kod = r["kod"]
            param_typ = r.get("typ")
            param_grupa = r.get("grupa")

            per_batch = wyniki_flat.get(kod) if (wyniki_flat and kod) else None
            if isinstance(per_batch, dict):
                batch_wartosc = per_batch.get("wartosc", per_batch.get("value", ""))
                batch_text = per_batch.get("wartosc_text")
            else:
                batch_wartosc = per_batch
                batch_text = None

            if param_typ == "jakosciowy":
                # Per-batch wartosc_text first; fall back to cert-level qualitative_result.
                result = (batch_text or "").strip() or (r["qualitative_result"] or "")
            elif param_grupa == "zewn" and batch_wartosc in (None, ""):
                # Empty external-lab value → visible placeholder (U+2212 minus sign).
                result = "\u2212"
            elif r["qualitative_result"]:
                result = r["qualitative_result"]
            else:
                # Numeric path — format with Polish decimal comma.
                if batch_wartosc is not None and batch_wartosc != "":
                    try:
                        result = _format_value(float(batch_wartosc), r["format"])
                    except (ValueError, TypeError):
                        result = str(batch_wartosc).replace(".", ",")
                else:
                    result = ""

            rows.append({
                "kod": kod,
                "name_pl": _md_to_richtext(name_pl, font=_settings["body_font_family"]),
                "name_en": _md_to_richtext(f"/{name_en}", font=_settings["body_font_family"]) if name_en else None,
                "requirement": _md_to_richtext(r["requirement"] or "", font=_settings["body_font_family"]),
                "method": method,
                "result": _md_to_richtext(result, font=_settings["body_font_family"]),
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
        "body_font_family":          _settings["body_font_family"],
        "header_font_family":        _settings["header_font_family"],
        "header_font_size_pt":       _settings["header_font_size_pt"],       # legacy
        "title_font_size_pt":        _settings["title_font_size_pt"],
        "product_name_font_size_pt": _settings["product_name_font_size_pt"],
        "body_font_size_pt":         _settings["body_font_size_pt"],
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
            # Fixed placeholder in preview — width-representative "1,0000"
            # lets the admin visually size the Wynik column without
            # guessing what real values might look like.
            result = "1,0000"
        # Fall back to globals when override is null (= inherit from registry).
        # name_en uses `is not None` so an empty-string override stays blank.
        name_pl_eff = param.get("name_pl") or param.get("name_pl_global") or ""
        ne_override = param.get("name_en")
        if ne_override is not None:
            _ne = ne_override
        else:
            _ne = param.get("name_en_global") or ""
        method_eff = param.get("method") or param.get("method_global") or ""
        format_eff = param.get("format") or param.get("format_global") or "1"
        rows.append({
            "name_pl": _md_to_richtext(name_pl_eff, font=_settings["body_font_family"]),
            "name_en": _md_to_richtext(f"/{_ne}", font=_settings["body_font_family"]) if _ne else None,
            "requirement": _md_to_richtext(param.get("requirement", "") or "", font=_settings["body_font_family"]),
            "method": method_eff,
            "result": _md_to_richtext(result, font=_settings["body_font_family"]),
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
        "body_font_family":          _settings["body_font_family"],
        "header_font_family":        _settings["header_font_family"],
        "header_font_size_pt":       _settings["header_font_size_pt"],       # legacy
        "title_font_size_pt":        _settings["title_font_size_pt"],
        "product_name_font_size_pt": _settings["product_name_font_size_pt"],
        "body_font_size_pt":         _settings["body_font_size_pt"],
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


_BODY_FONT_LITERAL = "TeX Gyre Bonum"   # 298× in word/document.xml
_HEADER_FONT_LITERAL = "Bookman Old Style"  # 12× in word/header1.xml
# styles.xml carries LibreOffice's default Latin pair (used by paragraph styles
# whose runs lack inline w:rFonts); without substitution Gotenberg falls back
# to LiberationSerif/Sans, clashing with Noto applied via the body/header
# sentinels above.
_STYLES_BODY_LITERAL = "Times New Roman"
_STYLES_HEADER_LITERAL = "Arial"


def _align_multiline_cells_to_bottom(doc) -> None:
    """Post-render: any param-table cell containing a <w:br/> (= line break)
    gets its vAlign flipped from center to bottom.

    Rationale: multi-line result/requirement cells (e.g. rozkład kwasów with
    9 stacked values) need to align to the bottom of the row so each line
    pairs visually with the chain label sitting at the same height in the
    name column. Single-line cells stay centered (default), avoiding the
    visual shift the user noticed when bottom-align was applied uniformly.
    """
    from lxml import etree
    WNS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

    if not doc.tables:
        return
    table = doc.tables[0]
    for row in table.rows[1:]:  # skip header
        for cell in row.cells:
            tcEl = cell._element
            # Only patch cells that contain at least one <w:br/>
            if tcEl.find(f'.//{{{WNS}}}br') is None:
                continue
            tcPr = tcEl.find(f'{{{WNS}}}tcPr')
            if tcPr is None:
                continue
            vAlign = tcPr.find(f'{{{WNS}}}vAlign')
            if vAlign is not None:
                vAlign.set(f'{{{WNS}}}val', 'bottom')


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
    _align_multiline_cells_to_bottom(tpl.docx)
    buf = io.BytesIO()
    tpl.save(buf)
    docx_bytes = buf.getvalue()
    body_font = context.get("body_font_family", _CERT_FONT)
    header_font = context.get("header_font_family", body_font)
    sizes = {
        "title_pt":        context.get("title_font_size_pt", 12),
        "product_name_pt": context.get("product_name_font_size_pt", 16),
        "body_pt":         context.get("body_font_size_pt", 11),
    }
    return _apply_typography_overrides(docx_bytes, body_font=body_font, header_font=header_font, sizes=sizes)


def _apply_typography_overrides(docx_bytes: bytes, body_font: str, header_font: str, sizes: dict) -> bytes:
    """Post-render byte-level substitution for typography settings.

    Args:
        docx_bytes: rendered docx zip bytes.
        body_font: font family for body text — replaces _BODY_FONT_LITERAL in
            word/document.xml only.
        header_font: font family for the page header (title + product name) —
            replaces _HEADER_FONT_LITERAL in word/header1.xml only.
        sizes: dict with keys:
            title_pt         — applied to sentinel 996 (Nagwek4 / title runs)
            product_name_pt  — applied to sentinel 997 (Nagwek8 / product name)
            body_pt          — applied to body w:sz/w:szCs w:val="22"

    Sentinel scheme in the template:
      * word/header1.xml — _HEADER_FONT_LITERAL replaced with header_font. Inline
        w:szCs (and w:sz) w:val="996" (title runs) → title_pt*2, "997"
        (product name run) → product_name_pt*2.
      * word/styles.xml — Nagwek4 w:sz="996", Nagwek8 w:sz="997".
      * word/document.xml — _BODY_FONT_LITERAL replaced with body_font. Body
        runs use w:sz/w:szCs="22" (11pt) plus "2" (1pt spacers). Only "22" is
        rewritten (exact value match).
    """
    import zipfile
    from io import BytesIO

    t2 = str(int(sizes["title_pt"]) * 2)
    p2 = str(int(sizes["product_name_pt"]) * 2)
    b2 = str(int(sizes["body_pt"]) * 2)

    in_buf = BytesIO(docx_bytes)
    out_buf = BytesIO()
    with zipfile.ZipFile(in_buf, "r") as zin, \
         zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.namelist():
            data = zin.read(item)
            if item == "word/document.xml":
                txt = data.decode("utf-8")
                if body_font and body_font != _BODY_FONT_LITERAL:
                    txt = re.sub(
                        r'(w:ascii|w:hAnsi|w:cs|w:eastAsia)="' + re.escape(_BODY_FONT_LITERAL) + r'"',
                        lambda m: f'{m.group(1)}="{body_font}"',
                        txt,
                    )
                # Body size — only w:val="22" (exact); w:val="2" (1pt spacer) is left alone.
                txt = txt.replace('w:sz w:val="22"', f'w:sz w:val="{b2}"')
                txt = txt.replace('w:szCs w:val="22"', f'w:szCs w:val="{b2}"')
                data = txt.encode("utf-8")
            elif item == "word/header1.xml":
                txt = data.decode("utf-8")
                if header_font and header_font != _HEADER_FONT_LITERAL:
                    txt = re.sub(
                        r'(w:ascii|w:hAnsi|w:cs|w:eastAsia)="' + re.escape(_HEADER_FONT_LITERAL) + r'"',
                        lambda m: f'{m.group(1)}="{header_font}"',
                        txt,
                    )
                txt = txt.replace('w:sz w:val="996"', f'w:sz w:val="{t2}"')
                txt = txt.replace('w:szCs w:val="996"', f'w:szCs w:val="{t2}"')
                txt = txt.replace('w:sz w:val="997"', f'w:sz w:val="{p2}"')
                txt = txt.replace('w:szCs w:val="997"', f'w:szCs w:val="{p2}"')
                data = txt.encode("utf-8")
            elif item == "word/styles.xml":
                txt = data.decode("utf-8")
                # Single-pass font substitution — sequential would corrupt
                # cases like body=Arial/header=Times where the second pass
                # would rewrite values produced by the first.
                styles_subs = {
                    _STYLES_BODY_LITERAL:   body_font,
                    _STYLES_HEADER_LITERAL: header_font,
                }
                styles_subs = {k: v for k, v in styles_subs.items() if v and v != k}
                if styles_subs:
                    pattern = (
                        r'(w:ascii|w:hAnsi|w:cs|w:eastAsia)="('
                        + "|".join(re.escape(k) for k in styles_subs)
                        + r')"'
                    )
                    txt = re.sub(
                        pattern,
                        lambda m: f'{m.group(1)}="{styles_subs[m.group(2)]}"',
                        txt,
                    )
                txt = txt.replace('w:sz w:val="996"', f'w:sz w:val="{t2}"')
                txt = txt.replace('w:sz w:val="997"', f'w:sz w:val="{p2}"')
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
