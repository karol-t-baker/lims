"""Certificate routes for the certs blueprint."""

import json as _json
from pathlib import Path

from flask import Response, abort, jsonify, render_template, request, send_file, session

from mbr.certs import certs_bp
from mbr.certs.generator import generate_certificate_pdf, get_required_fields, get_variants, save_certificate_data, load_config, _CONFIG_PATH
from mbr.certs.models import create_swiadectwo, list_swiadectwa
from mbr.db import db_session
from mbr.models import get_ebr, get_ebr_wyniki, get_mbr
from mbr.shared.decorators import login_required, role_required


# ---------------------------------------------------------------------------
# Certificate API
# ---------------------------------------------------------------------------

@certs_bp.route("/api/cert/templates")
@login_required
def api_cert_templates():
    produkt = request.args.get("produkt", "")
    if not produkt:
        return jsonify({"templates": []})
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


@certs_bp.route("/api/cert/generate", methods=["POST"])
@login_required
def api_cert_generate():
    data = request.get_json(silent=True) or {}
    ebr_id = data.get("ebr_id")
    variant_id = data.get("variant_id") or data.get("template_name")
    extra_fields = data.get("extra_fields", {})

    if not ebr_id or not variant_id:
        return jsonify({"ok": False, "error": "Missing ebr_id or variant_id"}), 400

    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if not ebr:
            return jsonify({"ok": False, "error": "EBR not found"}), 404
        if ebr.get("typ") != "zbiornik":
            return jsonify({"ok": False, "error": "Świadectwa tylko dla zbiorników"}), 400

        wyniki = get_ebr_wyniki(db, ebr_id)
        wyniki_flat = {}
        for sekcja_data in wyniki.values():
            for kod, row in sekcja_data.items():
                wyniki_flat[kod] = row

        # Resolve wystawil — prefer explicit from request, fallback to shift/session
        wystawil = (data.get("wystawil") or "").strip()
        if not wystawil:
            shift_ids = session.get("shift_workers", [])
            if shift_ids:
                workers = []
                for wid in shift_ids:
                    w = db.execute("SELECT imie, nazwisko FROM workers WHERE id=?", (wid,)).fetchone()
                    if w:
                        workers.append(w["imie"] + " " + w["nazwisko"])
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
                wystawil=wystawil,
            )
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

        # Save generation data to archive (for regeneration)
        import json as _json
        generation_data = {
            "produkt": ebr["produkt"],
            "variant_id": variant_id,
            "variant_label": variant_label,
            "nr_partii": ebr["nr_partii"],
            "dt_start": ebr.get("dt_start"),
            "wyniki_flat": {k: {"wartosc": v.get("wartosc"), "w_limicie": v.get("w_limicie")} for k, v in wyniki_flat.items()},
            "extra_fields": extra_fields,
            "wystawil": wystawil,
        }
        save_certificate_data(ebr["produkt"], variant_label, ebr["nr_partii"], generation_data)

        cert_id = create_swiadectwo(db, ebr_id, variant_label, ebr["nr_partii"], "regenerate", wystawil, data_json=_json.dumps(generation_data, ensure_ascii=False))

    # Return PDF as download to user's browser
    nr_only = ebr['nr_partii'].split('/')[0].strip()
    filename = f"{variant_label} {nr_only}.pdf"
    # HTTP headers must be ASCII-safe — replace em dash and encode
    filename_ascii = filename.replace('\u2014', '-').replace('\u2013', '-')
    from urllib.parse import quote
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename_ascii}\"; filename*=UTF-8''{quote(filename)}",
            "X-Cert-Id": str(cert_id),
        },
    )


@certs_bp.route("/api/cert/<int:cert_id>", methods=["DELETE"])
@login_required
def api_cert_delete(cert_id):
    with db_session() as db:
        row = db.execute("SELECT pdf_path FROM swiadectwa WHERE id = ?", (cert_id,)).fetchone()
        if row is None:
            return jsonify({"error": "not found"}), 404
        # Delete PDF file — handle both absolute and relative paths
        pdf_path = Path(row["pdf_path"])
        if not pdf_path.is_absolute():
            project_root = Path(__file__).parent.parent.parent
            pdf_path = (project_root / pdf_path).resolve()
        try:
            if pdf_path.exists():
                pdf_path.unlink()
        except Exception:
            pass  # File may already be deleted or inaccessible
        # Delete DB record
        db.execute("DELETE FROM swiadectwa WHERE id = ?", (cert_id,))
        db.commit()
    return jsonify({"ok": True})


@certs_bp.route("/api/cert/<int:cert_id>/pdf")
@login_required
def api_cert_pdf(cert_id):
    with db_session() as db:
        row = db.execute(
            "SELECT * FROM swiadectwa WHERE id = ?", (cert_id,)
        ).fetchone()
    if row is None:
        return "Nie znaleziono świadectwa", 404

    # Try regenerating from saved data_json (no file on disk)
    if row["data_json"]:
        import json as _json
        try:
            gen = _json.loads(row["data_json"])
            pdf_bytes = generate_certificate_pdf(
                gen["produkt"], gen["variant_id"], gen["nr_partii"],
                gen.get("dt_start"), gen.get("wyniki_flat", {}),
                gen.get("extra_fields", {}), wystawil=gen.get("wystawil", ""),
            )
            return Response(pdf_bytes, mimetype="application/pdf")
        except Exception as e:
            return f"Błąd regeneracji PDF: {e}", 500

    # Fallback: try reading from disk (legacy)
    pdf_path = Path(row["pdf_path"])
    if not pdf_path.is_absolute():
        project_root = Path(__file__).parent.parent.parent
        pdf_path = (project_root / pdf_path).resolve()
    if not pdf_path.exists() or pdf_path.is_dir():
        return "Plik PDF nie istnieje i brak danych do regeneracji.", 404
    return send_file(str(pdf_path), mimetype="application/pdf")


@certs_bp.route("/api/cert/list")
@login_required
def api_cert_list():
    ebr_id = request.args.get("ebr_id", type=int)
    if not ebr_id:
        return jsonify({"certs": []})
    with db_session() as db:
        certs = list_swiadectwa(db, ebr_id)
    return jsonify({"certs": certs})


# Cert config parameter endpoints removed — replaced by /api/parametry/cert/* endpoints
# in mbr/parametry/routes.py (parametry centralization, 2026-04-09)


# ---------------------------------------------------------------------------
# Product CRUD for cert config editor
# ---------------------------------------------------------------------------

def _read_config():
    """Read cert_config.json (fresh, no cache)."""
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return _json.load(f)


def _write_config(cfg):
    """Write cert_config.json atomically."""
    tmp = str(_CONFIG_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(cfg, f, ensure_ascii=False, indent=2)
    import os
    os.replace(tmp, str(_CONFIG_PATH))
    # Invalidate generator cache
    from mbr.certs import generator
    generator._cached_config = None


@certs_bp.route("/admin/wzory-cert")
@role_required("admin")
def admin_wzory_cert():
    return render_template("admin/wzory_cert.html")


@certs_bp.route("/api/cert/config/products")
@role_required("admin")
def api_cert_config_products():
    """List all products with summary info."""
    cfg = _read_config()
    products = cfg.get("products", {})
    result = []
    for key, prod in products.items():
        result.append({
            "key": key,
            "display_name": prod.get("display_name", key),
            "params_count": len(prod.get("parameters", [])),
            "variants_count": len(prod.get("variants", [])),
        })
    return jsonify({"ok": True, "products": result})


@certs_bp.route("/api/cert/config/product/<key>")
@role_required("admin")
def api_cert_config_product_get(key):
    """Full product data + optional DB metadata."""
    cfg = _read_config()
    products = cfg.get("products", {})
    if key not in products:
        return jsonify({"error": "Product not found"}), 404
    product = products[key]

    db_meta = None
    with db_session() as db:
        row = db.execute(
            "SELECT id, display_name, spec_number, cas_number, expiry_months, opinion_pl, opinion_en FROM produkty WHERE nazwa = ?",
            (key,),
        ).fetchone()
        if row:
            db_meta = {
                "id": row["id"],
                "display_name": row["display_name"],
                "spec_number": row["spec_number"],
                "cas_number": row["cas_number"],
                "expiry_months": row["expiry_months"],
                "opinion_pl": row["opinion_pl"],
                "opinion_en": row["opinion_en"],
            }

    return jsonify({"ok": True, "product": product, "db_meta": db_meta})


@certs_bp.route("/api/cert/config/product/<key>", methods=["PUT"])
@role_required("admin")
def api_cert_config_product_put(key):
    """Save product parameters + variants to cert_config.json."""
    cfg = _read_config()
    products = cfg.get("products", {})
    if key not in products:
        return jsonify({"error": "Product not found"}), 404

    data = request.get_json(silent=True) or {}
    parameters = data.get("parameters")
    variants = data.get("variants")

    # Validate parameters
    if parameters is not None:
        param_ids = set()
        for p in parameters:
            pid = p.get("id", "").strip()
            if not pid:
                return jsonify({"error": "Parameter missing id"}), 400
            if pid in param_ids:
                return jsonify({"error": f"Duplicate parameter id: {pid}"}), 400
            param_ids.add(pid)
            if not p.get("name_pl") or not p.get("name_en") or not p.get("requirement"):
                return jsonify({"error": f"Parameter '{pid}' missing name_pl, name_en, or requirement"}), 400
        products[key]["parameters"] = parameters

    # Validate variants
    if variants is not None:
        variant_ids = set()
        base_param_ids = {p["id"] for p in products[key].get("parameters", [])}
        for v in variants:
            vid = v.get("id", "").strip()
            if not vid:
                return jsonify({"error": "Variant missing id"}), 400
            if vid in variant_ids:
                return jsonify({"error": f"Duplicate variant id: {vid}"}), 400
            variant_ids.add(vid)
            if not v.get("label"):
                return jsonify({"error": f"Variant '{vid}' missing label"}), 400
            # Validate remove_parameters references
            overrides = v.get("overrides") or {}
            remove_params = overrides.get("remove_parameters", [])
            for rp in remove_params:
                if rp not in base_param_ids:
                    return jsonify({"error": f"Variant '{vid}' remove_parameters references unknown param: {rp}"}), 400
        products[key]["variants"] = variants

    # Sync display_name and meta fields if provided
    for field in ("display_name", "spec_number", "cas_number", "expiry_months", "opinion_pl", "opinion_en"):
        if field in data:
            products[key][field] = data[field]

    cfg["products"] = products
    _write_config(cfg)
    return jsonify({"ok": True})


@certs_bp.route("/api/cert/config/product", methods=["POST"])
@role_required("admin")
def api_cert_config_product_create():
    """Create a new product in cert_config.json and optionally in DB."""
    data = request.get_json(silent=True) or {}
    display_name = (data.get("display_name") or "").strip()
    if not display_name:
        return jsonify({"error": "display_name is required"}), 400

    key = display_name.replace(" ", "_")

    cfg = _read_config()
    products = cfg.get("products", {})
    if key in products:
        return jsonify({"error": f"Product '{key}' already exists"}), 409

    products[key] = {
        "display_name": display_name,
        "spec_number": data.get("spec_number", ""),
        "cas_number": data.get("cas_number", ""),
        "expiry_months": data.get("expiry_months", 12),
        "opinion_pl": data.get("opinion_pl", ""),
        "opinion_en": data.get("opinion_en", ""),
        "parameters": [],
        "variants": [
            {"id": "base", "label": display_name, "flags": []}
        ],
    }
    cfg["products"] = products
    _write_config(cfg)

    # Insert into produkty DB table if not exists
    with db_session() as db:
        existing = db.execute("SELECT id FROM produkty WHERE nazwa = ?", (key,)).fetchone()
        if not existing:
            db.execute(
                "INSERT INTO produkty (nazwa, display_name, spec_number, cas_number, expiry_months, opinion_pl, opinion_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key, display_name, data.get("spec_number", ""), data.get("cas_number", ""), data.get("expiry_months", 12), data.get("opinion_pl", ""), data.get("opinion_en", "")),
            )
            db.commit()

    return jsonify({"ok": True, "key": key})


@certs_bp.route("/api/cert/config/product/<key>", methods=["DELETE"])
@role_required("admin")
def api_cert_config_product_delete(key):
    """Delete a product from cert_config.json."""
    cfg = _read_config()
    products = cfg.get("products", {})
    if key not in products:
        return jsonify({"error": "Product not found"}), 404

    # Check for issued certificates
    warning = None
    with db_session() as db:
        row = db.execute(
            "SELECT COUNT(*) as cnt FROM swiadectwa WHERE nr_partii LIKE ?",
            (f"%{products[key].get('display_name', key)}%",),
        ).fetchone()
        if row and row["cnt"] > 0:
            warning = f"Found {row['cnt']} issued certificate(s) referencing this product."

    del products[key]
    cfg["products"] = products
    _write_config(cfg)

    result = {"ok": True}
    if warning:
        result["warning"] = warning
    return jsonify(result)


# ---------------------------------------------------------------------------
# PDF routes
# ---------------------------------------------------------------------------

from mbr.pdf_gen import generate_pdf  # noqa: E402


@certs_bp.route("/pdf/mbr/<int:mbr_id>")
@login_required
def pdf_mbr(mbr_id):
    """Empty card from MBR template."""
    with db_session() as db:
        mbr = get_mbr(db, mbr_id)
    if not mbr:
        abort(404)
    pdf_bytes = generate_pdf(mbr)
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=MBR_{mbr['produkt']}_v{mbr['wersja']}.pdf"})


@certs_bp.route("/pdf/ebr/<int:ebr_id>")
@login_required
def pdf_ebr(ebr_id):
    """Filled card from EBR + MBR."""
    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if not ebr:
            abort(404)
        mbr = get_mbr(db, ebr["mbr_id"])
        wyniki = get_ebr_wyniki(db, ebr_id)
    pdf_bytes = generate_pdf(mbr, ebr, wyniki)
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=EBR_{ebr['batch_id']}.pdf"})
