"""
COA Desktop App — local certificate generation with server DB sync.

Usage:
    pip install flask docxtpl docx2pdf requests
    python app.py

Opens browser at http://localhost:5050
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import requests
from docxtpl import DocxTemplate
from flask import Flask, Response, jsonify, render_template, request, send_file, session

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "batch_db.sqlite"
TEMPLATE_PATH = APP_DIR.parent / "mbr" / "templates" / "cert_master_template.docx"
CERT_CONFIG_PATH = APP_DIR.parent / "mbr" / "cert_config.json"
SWIADECTWA_DIR = DATA_DIR / "swiadectwa"

DEFAULT_SERVER = "https://192.168.100.171"
DEFAULT_OUTPUT_DIR = str(Path.home() / "Desktop" / "Swiadectwa")

app = Flask(__name__, template_folder="templates", static_folder="../mbr/static")
app.secret_key = "coa-local-app"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def load_cert_config() -> dict:
    with open(CERT_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _get_setting(key: str, default: str = "") -> str:
    """Read a setting from local settings.json."""
    sf = DATA_DIR / "settings.json"
    if sf.exists():
        with open(sf, encoding="utf-8") as f:
            return json.load(f).get(key, default)
    return default


def _set_setting(key: str, value: str):
    """Write a setting to local settings.json."""
    sf = DATA_DIR / "settings.json"
    settings = {}
    if sf.exists():
        with open(sf, encoding="utf-8") as f:
            settings = json.load(f)
    settings[key] = value
    with open(sf, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Routes — Sync
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("coa_main.html")


@app.route("/api/sync", methods=["POST"])
def api_sync():
    """Download DB from server."""
    server = _get_setting("server_url", DEFAULT_SERVER)
    try:
        r = requests.get(f"{server}/api/admin/db-snapshot", timeout=15, verify=False)
        r.raise_for_status()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(DB_PATH, "wb") as f:
            f.write(r.content)
        size_kb = len(r.content) // 1024
        return jsonify({"ok": True, "size_kb": size_kb})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Routes — Data
# ---------------------------------------------------------------------------

@app.route("/api/completed")
def api_completed():
    """List completed batches grouped by product."""
    if not DB_PATH.exists():
        return jsonify({"batches": [], "products": []})
    db = get_db()
    rows = db.execute("""
        SELECT eb.ebr_id, eb.nr_partii, mt.produkt, eb.typ, eb.dt_end, eb.nr_zbiornika
        FROM ebr_batches eb
        JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
        WHERE eb.status = 'completed'
        ORDER BY eb.dt_end DESC
    """).fetchall()
    batches = [dict(r) for r in rows]
    products = sorted(set(b["produkt"] for b in batches))
    db.close()
    return jsonify({"batches": batches, "products": products})


@app.route("/api/ebr/<int:ebr_id>")
def api_ebr_detail(ebr_id):
    """Get batch detail with wyniki."""
    db = get_db()
    ebr = db.execute("""
        SELECT eb.*, mt.produkt, mt.parametry_lab
        FROM ebr_batches eb
        JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
        WHERE eb.ebr_id = ?
    """, (ebr_id,)).fetchone()
    if not ebr:
        db.close()
        return jsonify({"error": "not found"}), 404
    d = dict(ebr)

    wyniki = db.execute(
        "SELECT kod_parametru, wartosc, w_limicie, min_limit, max_limit FROM ebr_wyniki WHERE ebr_id=?",
        (ebr_id,)
    ).fetchall()
    d["wyniki"] = {w["kod_parametru"]: dict(w) for w in wyniki}

    certs = db.execute(
        "SELECT id, template_name, dt_wystawienia, wystawil, nieaktualne FROM swiadectwa WHERE ebr_id=? ORDER BY dt_wystawienia DESC",
        (ebr_id,)
    ).fetchall()
    d["certs"] = [dict(c) for c in certs]

    db.close()
    return jsonify(d)


@app.route("/api/cert/templates")
def api_cert_templates():
    """Get available cert variants for a product."""
    produkt = request.args.get("produkt", "")
    cfg = load_cert_config()
    product_cfg = cfg.get("products", {}).get(produkt, {})
    variants = product_cfg.get("variants", [])
    result = []
    for v in variants:
        # Determine which fields need user input
        skip = {"has_rspo"}
        overrides = v.get("overrides", {})
        if overrides.get("avon_code"):
            skip.add("has_avon_code")
        if overrides.get("avon_name"):
            skip.add("has_avon_name")
        required = [f for f in v.get("flags", []) if f not in skip]
        result.append({
            "id": v["id"],
            "label": v["label"],
            "required_fields": required,
        })
    return jsonify({"templates": result})


# ---------------------------------------------------------------------------
# Routes — Certificate generation (local, using Word)
# ---------------------------------------------------------------------------

def _format_value(value, fmt="1"):
    try:
        places = int(fmt)
        return f"{float(value):.{places}f}".replace(".", ",")
    except (ValueError, TypeError):
        return str(value) if value else ""


def _days_in_month(year, month):
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


@app.route("/api/cert/generate", methods=["POST"])
def api_cert_generate():
    """Generate certificate PDF locally using Word."""
    data = request.get_json(silent=True) or {}
    ebr_id = data.get("ebr_id")
    variant_id = data.get("variant_id")
    extra_fields = data.get("extra_fields", {})
    wystawil = data.get("wystawil", "")

    if not ebr_id or not variant_id:
        return jsonify({"ok": False, "error": "Missing ebr_id or variant_id"}), 400

    db = get_db()
    ebr = db.execute("""
        SELECT eb.*, mt.produkt FROM ebr_batches eb
        JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id WHERE eb.ebr_id = ?
    """, (ebr_id,)).fetchone()
    if not ebr:
        db.close()
        return jsonify({"ok": False, "error": "EBR not found"}), 404

    wyniki_rows = db.execute(
        "SELECT kod_parametru, wartosc, w_limicie FROM ebr_wyniki WHERE ebr_id=?",
        (ebr_id,)
    ).fetchall()
    wyniki_flat = {w["kod_parametru"]: {"wartosc": w["wartosc"], "w_limicie": w["w_limicie"]} for w in wyniki_rows}
    db.close()

    produkt = ebr["produkt"]
    nr_partii = ebr["nr_partii"]
    dt_start = ebr["dt_start"]

    # Build context (same logic as server generator.py)
    cfg = load_cert_config()
    product_cfg = cfg["products"].get(produkt)
    if not product_cfg:
        return jsonify({"ok": False, "error": f"Product {produkt} not in cert_config"}), 404

    variant = None
    for v in product_cfg.get("variants", []):
        if v["id"] == variant_id:
            variant = v
            break
    if not variant:
        return jsonify({"ok": False, "error": f"Variant {variant_id} not found"}), 404

    # Spec & opinion (variant overrides)
    overrides = variant.get("overrides", {})
    spec_number = overrides.get("spec_number", product_cfg.get("spec_number", ""))
    opinion_pl = overrides.get("opinion_pl", product_cfg.get("opinion_pl", ""))
    opinion_en = overrides.get("opinion_en", product_cfg.get("opinion_en", ""))

    # Parameters — apply remove/add overrides
    params = list(product_cfg.get("parameters", []))
    remove_ids = set(overrides.get("remove_parameters", []))
    if remove_ids:
        params = [p for p in params if p["id"] not in remove_ids]
    for p in overrides.get("add_parameters", []):
        params.append(p)

    # Build rows
    rows = []
    for param in params:
        if param.get("qualitative_result"):
            result = param["qualitative_result"]
        elif param.get("data_field") and param["data_field"] in wyniki_flat:
            raw = wyniki_flat[param["data_field"]]
            val = raw.get("wartosc", "")
            result = _format_value(val, param.get("format", "1")) if val not in (None, "") else ""
        else:
            result = ""
        rows.append({
            "name_pl": param.get("name_pl", ""),
            "name_en": param.get("name_en", ""),
            "requirement": param.get("requirement", ""),
            "method": param.get("method", ""),
            "result": result,
        })

    # Dates
    dt_wystawienia = date.today().strftime("%Y-%m-%d")
    dt_produkcji = ""
    dt_waznosci = ""
    if dt_start:
        try:
            dt_obj = datetime.fromisoformat(dt_start).date() if "T" in str(dt_start) else datetime.strptime(str(dt_start)[:10], "%Y-%m-%d").date()
            dt_produkcji = dt_obj.strftime("%Y-%m-%d")
            em = product_cfg.get("expiry_months", 12)
            year = dt_obj.year + (dt_obj.month - 1 + em) // 12
            month = (dt_obj.month - 1 + em) % 12 + 1
            day = min(dt_obj.day, _days_in_month(year, month))
            dt_waznosci = date(year, month, day).strftime("%Y-%m-%d")
        except Exception:
            pass

    # Flags
    flags = set(variant.get("flags", []))
    order_number = extra_fields.get("order_number", "") if "has_order_number" in flags else ""
    certificate_number = extra_fields.get("certificate_number", "") if "has_certificate_number" in flags else ""
    has_rspo = "has_rspo" in flags
    rspo_number = cfg.get("rspo_number", "CU-RSPO SCC-857488")
    rspo_text = rspo_number if has_rspo else ""
    if has_rspo and "has_certificate_number" not in flags:
        certificate_number = rspo_text
        rspo_text = ""
    avon_code = overrides.get("avon_code") or extra_fields.get("avon_code", "") if "has_avon_code" in flags else ""
    avon_name = overrides.get("avon_name") or extra_fields.get("avon_name", "") if "has_avon_name" in flags else ""

    context = {
        "company": cfg["company"],
        "footer": cfg["footer"],
        "display_name": product_cfg["display_name"] + (" MB" if has_rspo else ""),
        "spec_number": spec_number,
        "cas_number": product_cfg.get("cas_number", ""),
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

    # Render docx
    try:
        tpl = DocxTemplate(str(TEMPLATE_PATH))
        tpl.render(context)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Template render error: {e}"}), 500

    # Save to output dir
    output_dir = Path(_get_setting("output_dir", DEFAULT_OUTPUT_DIR))
    variant_label = variant["label"]
    year_dir = output_dir / str(date.today().year) / product_cfg["display_name"]
    year_dir.mkdir(parents=True, exist_ok=True)

    safe_nr = nr_partii.replace("/", "_")
    base_name = f"{variant_label} {safe_nr}"

    # Docx path (temp)
    docx_path = year_dir / f"{base_name}.docx"
    pdf_path = year_dir / f"{base_name}.pdf"

    tpl.save(str(docx_path))

    # Convert docx → pdf using Word (docx2pdf)
    try:
        from docx2pdf import convert
        convert(str(docx_path), str(pdf_path))
        docx_path.unlink()  # Remove temp docx
    except Exception as e:
        return jsonify({"ok": False, "error": f"PDF conversion error: {e}. Is Word installed?"}), 500

    # Save cert record to local DB
    try:
        db = get_db()
        now = datetime.now().isoformat(timespec="seconds")
        db.execute(
            "INSERT INTO swiadectwa (ebr_id, template_name, nr_partii, pdf_path, dt_wystawienia, wystawil) VALUES (?,?,?,?,?,?)",
            (ebr_id, variant_label, nr_partii, str(pdf_path), now, wystawil),
        )
        db.commit()
        db.close()
    except Exception:
        pass  # Non-critical

    return jsonify({"ok": True, "pdf_path": str(pdf_path)})


# ---------------------------------------------------------------------------
# Routes — Settings
# ---------------------------------------------------------------------------

@app.route("/api/settings", methods=["GET", "PUT"])
def api_settings():
    if request.method == "PUT":
        data = request.get_json(silent=True) or {}
        for k, v in data.items():
            _set_setting(k, v)
        return jsonify({"ok": True})
    return jsonify({
        "server_url": _get_setting("server_url", DEFAULT_SERVER),
        "output_dir": _get_setting("output_dir", DEFAULT_OUTPUT_DIR),
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    import webbrowser
    webbrowser.open("http://localhost:5050")
    # Suppress urllib3 InsecureRequestWarning
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    app.run(host="127.0.0.1", port=5050, debug=False)
