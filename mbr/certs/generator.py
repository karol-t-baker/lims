"""Config-driven certificate PDF generation (v2).

Replaces the old docx-parsing system (cert_gen.py) with a config-driven approach
using cert_config.json for product/variant definitions.

Rendering: docxtpl fills .docx master template → Gotenberg converts to PDF.
"""
import copy
import io
import json
import tempfile
from datetime import date, datetime
from pathlib import Path

import requests
from docxtpl import DocxTemplate

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
    """Return list of {id, label, flags} for a product.

    Product key uses underscores (e.g. "Chegina_K40GLOL").
    Also tries replacing spaces with underscores if not found directly.
    """
    cfg = load_config()
    products = cfg["products"]

    key = produkt
    if key not in products:
        key = produkt.replace(" ", "_")
    if key not in products:
        return []

    product_cfg = products[key]
    return [
        {"id": v["id"], "label": v["label"], "flags": v.get("flags", [])}
        for v in product_cfg.get("variants", [])
    ]


# ---------------------------------------------------------------------------
# 3. get_required_fields
# ---------------------------------------------------------------------------
def get_required_fields(produkt: str, variant_id: str) -> list[str]:
    """Return flags that need user input for a variant.

    Filters out 'has_rspo' (not user-entered).
    """
    cfg = load_config()
    products = cfg["products"]

    key = produkt if produkt in products else produkt.replace(" ", "_")
    if key not in products:
        return []

    product_cfg = products[key]
    for v in product_cfg.get("variants", []):
        if v["id"] == variant_id:
            skip = {"has_rspo"}
            # Skip avon fields if already defined in variant overrides
            overrides = v.get("overrides", {})
            if overrides.get("avon_code"):
                skip.add("has_avon_code")
            if overrides.get("avon_name"):
                skip.add("has_avon_name")
            return [f for f in v.get("flags", []) if f not in skip]
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
# 4b. _build_rows_from_db
# ---------------------------------------------------------------------------
def _build_rows_from_db(db, produkt: str, wyniki_flat: dict) -> list[dict]:
    """Build certificate rows from parametry_cert + parametry_analityczne (DB source).

    Returns list of dicts with keys: _kod, name_pl, name_en, requirement, method, result.
    _kod is internal (for variant filtering), stripped by caller.
    """
    rows_db = db.execute(
        "SELECT pc.*, pa.kod, pa.label, pa.name_en, pa.method_code, pa.precision as pa_precision "
        "FROM parametry_cert pc "
        "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
        "WHERE pc.produkt = ? ORDER BY pc.kolejnosc",
        (produkt,),
    ).fetchall()

    rows = []
    for r in rows_db:
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
            "_kod": r["kod"] or "",
            "name_pl": r["label"] or "",
            "name_en": r["name_en"] or "",
            "requirement": r["requirement"] or "",
            "method": r["method_code"] or "",
            "result": result,
        })

    return rows


# ---------------------------------------------------------------------------
# 4c. _get_product_meta
# ---------------------------------------------------------------------------
def _get_product_meta(db, produkt: str) -> dict | None:
    """Read product metadata from produkty table.

    Returns dict with display_name, spec_number, cas_number, expiry_months,
    opinion_pl, opinion_en — or None if not found.
    """
    row = db.execute(
        "SELECT display_name, spec_number, cas_number, expiry_months, "
        "opinion_pl, opinion_en FROM produkty WHERE nazwa = ?",
        (produkt,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


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
    """Build Jinja2 context dict for certificate rendering.

    Args:
        produkt: Product key (e.g. "Chegina_K40GLOL").
        variant_id: Variant id (e.g. "base", "loreal").
        nr_partii: Batch number string.
        dt_start: Production start date (date, datetime, or ISO string).
        wyniki_flat: Lab results dict {kod: value_or_dict}.
        extra_fields: Optional dict with user-entered fields (order_number, etc.).

    Returns:
        Context dict ready for template rendering.
    """
    cfg = load_config()
    products = cfg["products"]

    key = produkt if produkt in products else produkt.replace(" ", "_")
    if key not in products:
        raise ValueError(f"Unknown product: {produkt}")

    product_cfg = products[key]

    # Find variant
    variant = None
    for v in product_cfg.get("variants", []):
        if v["id"] == variant_id:
            variant = v
            break
    if variant is None:
        raise ValueError(f"Unknown variant '{variant_id}' for product '{produkt}'")

    parameters = copy.deepcopy(product_cfg["parameters"])

    overrides = variant.get("overrides", {})

    # Product metadata — DB-first, fallback to cert_config.json
    from mbr.db import db_session as _db_session
    product_meta = None
    try:
        with _db_session() as _pdb:
            product_meta = _get_product_meta(_pdb, key)
    except Exception:
        pass

    if product_meta and product_meta.get("display_name"):
        _display_name = product_meta["display_name"]
        _spec_number = product_meta["spec_number"] or product_cfg.get("spec_number", "")
        _cas_number = product_meta["cas_number"] or product_cfg.get("cas_number", "")
        _expiry_months = product_meta["expiry_months"] or product_cfg.get("expiry_months", 12)
        _opinion_pl = product_meta["opinion_pl"] or product_cfg.get("opinion_pl", "")
        _opinion_en = product_meta["opinion_en"] or product_cfg.get("opinion_en", "")
    else:
        _display_name = product_cfg.get("display_name", key)
        _spec_number = product_cfg.get("spec_number", "")
        _cas_number = product_cfg.get("cas_number", "")
        _expiry_months = product_cfg.get("expiry_months", 12)
        _opinion_pl = product_cfg.get("opinion_pl", "")
        _opinion_en = product_cfg.get("opinion_en", "")

    # Apply variant overrides on top of base values
    spec_number = overrides.get("spec_number", _spec_number)
    opinion_pl = overrides.get("opinion_pl", _opinion_pl)
    opinion_en = overrides.get("opinion_en", _opinion_en)

    # Remove parameters (for config fallback)
    remove_ids = set(overrides.get("remove_parameters", []))

    # Build rows — DB-first with config fallback
    rows = []
    use_db = False
    try:
        with _db_session() as db:
            cert_count = db.execute(
                "SELECT COUNT(*) as c FROM parametry_cert WHERE produkt=?", (key,)
            ).fetchone()["c"]
            if cert_count > 0:
                use_db = True
                db_rows = _build_rows_from_db(db, key, wyniki_flat)

                # Variant: remove_parameters
                if remove_ids:
                    remove_kods = set()
                    for p in product_cfg.get("parameters", []):
                        if p["id"] in remove_ids:
                            remove_kods.add(p.get("data_field") or p["id"])
                    db_rows = [r for r in db_rows if r.get("_kod") not in remove_kods]

                # Variant: add_parameters (still from config JSON)
                for ap in overrides.get("add_parameters", []):
                    result = ""
                    if ap.get("qualitative_result"):
                        result = ap["qualitative_result"]
                    elif ap.get("data_field") and ap["data_field"] in wyniki_flat:
                        raw = wyniki_flat[ap["data_field"]]
                        val = raw.get("wartosc", raw) if isinstance(raw, dict) else raw
                        if val is not None and val != "":
                            try:
                                result = _format_value(float(val), ap.get("format", "1"))
                            except (ValueError, TypeError):
                                result = str(val).replace(".", ",")
                    db_rows.append({
                        "name_pl": ap.get("name_pl", ""),
                        "name_en": ap.get("name_en", ""),
                        "requirement": ap.get("requirement", ""),
                        "method": ap.get("method", ""),
                        "result": result,
                    })

                # Strip internal _kod field
                rows = [{k: v for k, v in r.items() if k != "_kod"} for r in db_rows]
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("parametry_cert DB read failed, falling back to config: %s", e)
        use_db = False

    if not use_db:
        # Original config-based logic (unchanged fallback)
        if remove_ids:
            parameters = [p for p in parameters if p["id"] not in remove_ids]

        # Add parameters
        add_params = overrides.get("add_parameters", [])
        if add_params:
            parameters.extend(copy.deepcopy(add_params))

        rows = []
        for param in parameters:
            # Determine result value
            result = ""
            if param.get("qualitative_result"):
                result = param["qualitative_result"]
            elif param.get("data_field") and param["data_field"] in wyniki_flat:
                raw = wyniki_flat[param["data_field"]]
                # wyniki_flat values can be dicts with a 'wartosc' key or raw values
                if isinstance(raw, dict):
                    val = raw.get("wartosc", raw.get("value", ""))
                else:
                    val = raw
                if val is not None and val != "":
                    try:
                        result = _format_value(float(val), param.get("format", "1"))
                    except (ValueError, TypeError):
                        result = str(val).replace(".", ",")

            rows.append({
                "name_pl": param["name_pl"],
                "name_en": param["name_en"],
                "requirement": param["requirement"],
                "method": param.get("method", ""),
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
    flags = set(variant.get("flags", []))

    order_number = extra.get("order_number", "") if "has_order_number" in flags else ""
    certificate_number = extra.get("certificate_number", "") if "has_certificate_number" in flags else ""
    has_rspo = "has_rspo" in flags
    rspo_number = cfg.get("rspo_number", "CU-RSPO SCC-857488")
    rspo_text = rspo_number if has_rspo else ""
    # If MB variant (has_rspo but no has_certificate_number), auto-fill certificate_number with RSPO
    if has_rspo and "has_certificate_number" not in flags:
        certificate_number = rspo_text
        rspo_text = ""
    # Avon fields: prefer static values from variant overrides, fallback to user input
    overrides = variant.get("overrides", {})
    avon_code = overrides.get("avon_code") or extra.get("avon_code", "") if "has_avon_code" in flags else ""
    avon_name = overrides.get("avon_name") or extra.get("avon_name", "") if "has_avon_name" in flags else ""

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
    }


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


def _docxtpl_render(context: dict) -> bytes:
    """Render the master .docx template with context, return .docx bytes."""
    tpl = DocxTemplate(str(_TEMPLATE_PATH))
    tpl.render(_escape_xml_chars(context))
    buf = io.BytesIO()
    tpl.save(buf)
    return buf.getvalue()


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
