"""
COA Desktop App — same UI as server, local cert generation with Word.

Usage:
    pip install flask docxtpl docx2pdf requests bcrypt
    python app.py

Opens browser at http://localhost:5050
"""

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Path resolution — supports PyInstaller frozen mode
# ---------------------------------------------------------------------------

_FROZEN = getattr(sys, "frozen", False)

_BUNDLE_DIR = os.environ.get("LABCORE_BUNDLE_DIR")
if _BUNDLE_DIR:
    # Launched via launcher.py (frozen or dev) — LABCORE_BUNDLE_DIR = repo root
    sys.path.insert(0, _BUNDLE_DIR)
else:
    # Direct python app.py (legacy dev mode)
    sys.path.insert(0, str(Path(__file__).parent.parent))

APP_DIR = Path(sys._MEIPASS) if _FROZEN else Path(__file__).parent

_DATA_DIR_ENV = os.environ.get("LABCORE_DATA_DIR")
DATA_DIR = Path(_DATA_DIR_ENV) if _DATA_DIR_ENV else APP_DIR / "data"
DB_PATH = DATA_DIR / "batch_db.sqlite"
MBR_DIR = Path(sys._MEIPASS) / "mbr" if _FROZEN else APP_DIR.parent / "mbr"

DEFAULT_SERVER = "http://labcore.local:5001"
DEFAULT_OUTPUT_DIR = str(Path.home() / "Desktop" / "Swiadectwa")
DEFAULT_BACKUP_DIR = str(Path.home() / "Desktop" / "Backupy_LIMS")

import requests as http_requests
from flask import Flask, jsonify, request, session, redirect, url_for


def _find_soffice() -> str:
    """Find LibreOffice soffice binary."""
    import shutil
    # Check PATH first
    found = shutil.which("soffice")
    if found:
        return found
    # Common Windows locations
    if sys.platform == "win32":
        for prog in [os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                     os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")]:
            candidate = Path(prog) / "LibreOffice" / "program" / "soffice.exe"
            if candidate.exists():
                return str(candidate)
    raise FileNotFoundError(
        "LibreOffice nie znaleziony. Zainstaluj LibreOffice: https://www.libreoffice.org/download/"
    )


def _word_convert(docx_path: str, pdf_path: str):
    """Convert docx to pdf using LibreOffice headless."""
    import subprocess
    import tempfile
    soffice = _find_soffice()
    # Use unique user profile to avoid lock conflicts on concurrent/sequential calls
    with tempfile.TemporaryDirectory(prefix="lo_") as tmpdir:
        result = subprocess.run([
            soffice, "--headless",
            f"--env:UserInstallation=file:///{tmpdir.replace(os.sep, '/')}",
            "--convert-to", "pdf",
            "--outdir", str(Path(pdf_path).parent),
            docx_path,
        ], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or "LibreOffice conversion failed")
    # soffice names output by input filename — rename if needed
    generated = Path(pdf_path).parent / (Path(docx_path).stem + ".pdf")
    if generated != Path(pdf_path) and generated.exists():
        generated.rename(pdf_path)


def _get_setting(key, default=""):
    sf = DATA_DIR / "settings.json"
    if sf.exists():
        with open(sf, encoding="utf-8") as f:
            val = json.load(f).get(key, "")
            return val if val else default
    return default


def _set_setting(key, value):
    sf = DATA_DIR / "settings.json"
    settings = {}
    if sf.exists():
        with open(sf, encoding="utf-8") as f:
            settings = json.load(f)
    settings[key] = value
    with open(sf, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Patch mbr.db to use local DB path BEFORE importing mbr
# ---------------------------------------------------------------------------

DATA_DIR.mkdir(parents=True, exist_ok=True)

import mbr.db as _mbr_db
_mbr_db.DB_PATH = DB_PATH

# Now import mbr app factory
from mbr.app import create_app

app = create_app()
app.config["SERVER_NAME"] = None
app.secret_key = "coa-local-app"


# ---------------------------------------------------------------------------
# Auto-login as laborant_coa on every request
# ---------------------------------------------------------------------------

@app.before_request
def auto_login():
    if "user" not in session:
        session["user"] = {
            "login": "laborant_coa",
            "rola": "laborant_coa",
            "imie_nazwisko": "COA",
        }


# Override index to go straight to szarze
@app.route("/coa-home")
def coa_home():
    return redirect(url_for("laborant.szarze_list"))


# ---------------------------------------------------------------------------
# Sync endpoint — download DB from server
# ---------------------------------------------------------------------------

@app.route("/api/coa/sync", methods=["POST"])
def api_coa_sync():
    server = _get_setting("server_url", DEFAULT_SERVER)

    # One-time migration: if old timestamp-based setting exists but seq doesn't, start from 0
    if _get_setting("last_sync_seq", "") == "" and _get_setting("last_sync", "") != "":
        _set_setting("last_sync_seq", "0")

    last_seq = int(_get_setting("last_sync_seq", "0"))
    ref_hash = _get_setting("ref_hash", "")

    # If local DB is empty, force full sync from seq 0
    try:
        db_check = _mbr_db.get_db()
        local_count = db_check.execute("SELECT COUNT(*) FROM ebr_batches").fetchone()[0]
        db_check.close()
        if local_count == 0:
            last_seq = 0
            ref_hash = ""
    except Exception:
        last_seq = 0
        ref_hash = ""

    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = http_requests.get(
            f"{server}/api/completed?since={last_seq}&ref_hash={ref_hash}",
            timeout=15, verify=False,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            return jsonify({"ok": False, "error": data.get("error", "Unknown")}), 500

        db = _mbr_db.get_db()
        counts = {"new": 0, "updated": 0}

        # Upsert reference tables (only if server sent them — hash changed)
        if data.get("reference"):
            for table, rows in data["reference"].items():
                if not rows:
                    continue
                cols = list(rows[0].keys())
                placeholders = ",".join("?" * len(cols))
                col_names = ",".join(cols)
                for row in rows:
                    vals = [row[c] for c in cols]
                    db.execute(
                        f"INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})",
                        vals,
                    )

        # Upsert batches
        for row in data.get("batches", []):
            cols = list(row.keys())
            placeholders = ",".join("?" * len(cols))
            col_names = ",".join(cols)
            pk = row["ebr_id"]
            existing = db.execute("SELECT ebr_id FROM ebr_batches WHERE ebr_id=?", (pk,)).fetchone()
            db.execute(f"INSERT OR REPLACE INTO ebr_batches ({col_names}) VALUES ({placeholders})",
                       [row[c] for c in cols])
            counts["updated" if existing else "new"] += 1

        # Upsert wyniki
        for row in data.get("wyniki", []):
            cols = list(row.keys())
            placeholders = ",".join("?" * len(cols))
            col_names = ",".join(cols)
            db.execute(f"INSERT OR REPLACE INTO ebr_wyniki ({col_names}) VALUES ({placeholders})",
                       [row[c] for c in cols])

        # Upsert swiadectwa
        for row in data.get("swiadectwa", []):
            cols = list(row.keys())
            placeholders = ",".join("?" * len(cols))
            col_names = ",".join(cols)
            db.execute(f"INSERT OR REPLACE INTO swiadectwa ({col_names}) VALUES ({placeholders})",
                       [row[c] for c in cols])

        db.commit()
        db.close()

        # Save new sync seq from server
        new_seq = data.get("max_seq", last_seq)
        _set_setting("last_sync_seq", str(new_seq))
        if data.get("ref_hash"):
            _set_setting("ref_hash", data["ref_hash"])

        # Backup max once per day
        import shutil
        backup_dir = Path(_get_setting("backup_dir", DEFAULT_BACKUP_DIR))
        backup_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        today_backup = backup_dir / f"batch_db_{today}.sqlite"
        if not today_backup.exists():
            shutil.copy2(DB_PATH, today_backup)
            backups = sorted(backup_dir.glob("batch_db_*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in backups[5:]:
                old.unlink()

        n_batches = len(data.get("batches", []))
        total = data.get("total_completed", "?")
        return jsonify({
            "ok": True,
            "new": counts["new"],
            "updated": counts["updated"],
            "batches_synced": n_batches,
            "total_on_server": total,
            "sync_seq": new_seq,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/coa/sync-full", methods=["POST"])
def api_coa_sync_full():
    """Full DB download — fallback if delta fails or first setup."""
    server = _get_setting("server_url", DEFAULT_SERVER)
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = http_requests.get(f"{server}/api/admin/db-snapshot", timeout=30, verify=False)
        r.raise_for_status()
        with open(DB_PATH, "wb") as f:
            f.write(r.content)
        _set_setting("last_sync_seq", "0")
        size_kb = len(r.content) // 1024
        return jsonify({"ok": True, "size_kb": size_kb, "mode": "full"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# COA Settings endpoint
# ---------------------------------------------------------------------------

@app.route("/api/coa/settings", methods=["GET", "PUT"])
def api_coa_settings():
    if request.method == "PUT":
        data = request.get_json(silent=True) or {}
        for k, v in data.items():
            _set_setting(k, v)
        return jsonify({"ok": True})
    return jsonify({
        "server_url": _get_setting("server_url", DEFAULT_SERVER),
        "output_dir": _get_setting("output_dir", DEFAULT_OUTPUT_DIR),
        "backup_dir": _get_setting("backup_dir", DEFAULT_BACKUP_DIR),
    })


# ---------------------------------------------------------------------------
# Override cert generation — use local Word instead of Gotenberg
# ---------------------------------------------------------------------------

from mbr.certs import certs_bp
from mbr.certs.generator import load_config, _CONFIG_PATH, get_variants, get_required_fields
from mbr.certs.generator import _format_value, _days_in_month

# Override server cert generate with local LibreOffice version
def coa_cert_generate():
    """Generate certificate PDF locally using Word (docx2pdf)."""
    from docxtpl import DocxTemplate

    data = request.get_json(silent=True) or {}
    ebr_id = data.get("ebr_id")
    variant_id = data.get("variant_id") or data.get("template_name")
    extra_fields = data.get("extra_fields", {})
    wystawil = data.get("wystawil", "")

    if not ebr_id or not variant_id:
        return jsonify({"ok": False, "error": "Missing ebr_id or variant_id"}), 400

    from mbr.db import db_session
    from mbr.models import get_ebr, get_ebr_wyniki

    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if not ebr:
            return jsonify({"ok": False, "error": "EBR not found"}), 404

        wyniki = get_ebr_wyniki(db, ebr_id)
        wyniki_flat = {}
        for sekcja_data in wyniki.values():
            for kod, row in sekcja_data.items():
                wyniki_flat[kod] = row

    produkt = ebr["produkt"]
    nr_partii = ebr["nr_partii"]

    cfg = load_config(reload=True)
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

    variant_label = variant["label"]
    overrides = variant.get("overrides", {})
    spec_number = overrides.get("spec_number", product_cfg.get("spec_number", ""))
    opinion_pl = overrides.get("opinion_pl", product_cfg.get("opinion_pl", ""))
    opinion_en = overrides.get("opinion_en", product_cfg.get("opinion_en", ""))

    # Parameters
    params = list(product_cfg.get("parameters", []))
    remove_ids = set(overrides.get("remove_parameters", []))
    if remove_ids:
        params = [p for p in params if p["id"] not in remove_ids]
    for p in overrides.get("add_parameters", []):
        params.append(p)

    rows = []
    for param in params:
        if param.get("qualitative_result"):
            result = param["qualitative_result"]
        elif param.get("data_field") and param["data_field"] in wyniki_flat:
            raw = wyniki_flat[param["data_field"]]
            val = raw.get("wartosc", raw.get("value", ""))
            result = _format_value(float(val), param.get("format", "1")) if val not in (None, "") else ""
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
    dt_start = ebr.get("dt_start")
    dt_wystawienia = date.today().strftime("%Y-%m-%d")
    dt_produkcji = dt_waznosci = ""
    if dt_start:
        try:
            dt_obj = datetime.fromisoformat(str(dt_start)).date() if "T" in str(dt_start) else datetime.strptime(str(dt_start)[:10], "%Y-%m-%d").date()
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
    template_path = MBR_DIR / "templates" / "cert_master_template.docx"
    try:
        tpl = DocxTemplate(str(template_path))
        tpl.render(context)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Template error: {e}"}), 500

    # Save to output dir
    output_dir = Path(_get_setting("output_dir", DEFAULT_OUTPUT_DIR))
    year_dir = output_dir / str(date.today().year) / product_cfg["display_name"]
    year_dir.mkdir(parents=True, exist_ok=True)

    safe_nr = nr_partii.replace("/", "_")
    base_name = f"{variant_label} {safe_nr}"
    docx_path = year_dir / f"{base_name}.docx"
    pdf_path = year_dir / f"{base_name}.pdf"

    tpl.save(str(docx_path))

    # Convert docx → pdf using Word (hidden, kept alive for speed)
    try:
        _word_convert(str(docx_path.resolve()), str(pdf_path.resolve()))
        docx_path.unlink()
    except Exception as e:
        return jsonify({"ok": False, "error": f"PDF error: {e}. Is Word installed?"}), 500

    # Record in local DB
    try:
        with db_session() as db:
            now = datetime.now().isoformat(timespec="seconds")
            db.execute(
                "INSERT INTO swiadectwa (ebr_id, template_name, nr_partii, pdf_path, dt_wystawienia, wystawil) VALUES (?,?,?,?,?,?)",
                (ebr_id, variant_label, nr_partii, str(pdf_path), now, wystawil),
            )
            db.commit()
    except Exception:
        pass

    return jsonify({"ok": True, "pdf_path": str(pdf_path)})

# Replace server's cert generate with our local version
app.view_functions["certs.api_cert_generate"] = coa_cert_generate


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    if not DB_PATH.exists():
        from mbr.models import init_mbr_tables
        with _mbr_db.db_session() as db:
            init_mbr_tables(db)

    print("=" * 50)
    print("  LabCore COA — http://localhost:5050")
    print("=" * 50)

    if os.environ.get("LABCORE_NO_BROWSER") != "1":
        import webbrowser
        webbrowser.open("http://localhost:5050")

    app.run(host="127.0.0.1", port=5050, debug=False)
