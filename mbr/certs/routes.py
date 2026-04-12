"""Certificate routes for the certs blueprint."""

import json as _json
from pathlib import Path

from flask import Response, abort, jsonify, render_template, request, send_file, session

from mbr.certs import certs_bp
from mbr.certs.generator import generate_certificate_pdf, get_required_fields, get_variants, save_certificate_data, load_config, build_preview_context, _docxtpl_render, _gotenberg_convert
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
        if ebr.get("typ") not in ("zbiornik", "platkowanie"):
            return jsonify({"ok": False, "error": "Świadectwa tylko dla zbiorników i płatkowania"}), 400

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
    filename = f"Świadectwo_certificate - {variant_label} {nr_only}.pdf"
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
# Product CRUD for cert config editor (DB-backed)
# ---------------------------------------------------------------------------


@certs_bp.route("/admin/wzory-cert")
@role_required("admin")
def admin_wzory_cert():
    return render_template("admin/wzory_cert.html")


@certs_bp.route("/api/cert/config/products")
@role_required("admin")
def api_cert_config_products():
    """List all products that have cert variants defined (from DB)."""
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


@certs_bp.route("/api/cert/config/product/<key>")
@role_required("admin")
def api_cert_config_product_get(key):
    """Full product data from DB, same JSON shape as the old JSON-based endpoint."""
    with db_session() as db:
        prod_row = db.execute(
            "SELECT id, nazwa, display_name, spec_number, cas_number, expiry_months, opinion_pl, opinion_en "
            "FROM produkty WHERE nazwa = ?",
            (key,),
        ).fetchone()
        if not prod_row:
            return jsonify({"error": "Product not found"}), 404

        # Check that cert_variants exist for this product
        has_variants = db.execute(
            "SELECT 1 FROM cert_variants WHERE produkt = ? LIMIT 1", (key,)
        ).fetchone()
        if not has_variants:
            return jsonify({"error": "Product not found"}), 404

        # Build product object matching old JSON shape
        product = {
            "display_name": prod_row["display_name"] or key,
            "spec_number": prod_row["spec_number"] or "",
            "cas_number": prod_row["cas_number"] or "",
            "expiry_months": prod_row["expiry_months"] or 12,
            "opinion_pl": prod_row["opinion_pl"] or "",
            "opinion_en": prod_row["opinion_en"] or "",
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
        product["parameters"] = parameters

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
                "flags": _json.loads(vr["flags"] or "[]"),
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

            remove_params_ids = _json.loads(vr["remove_params"] or "[]")
            if remove_params_ids:
                remove_kods = []
                for pid in remove_params_ids:
                    r = db.execute("SELECT kod FROM parametry_analityczne WHERE id=?", (pid,)).fetchone()
                    remove_kods.append(r["kod"] if r and r["kod"] else f"param_{pid}")
                overrides["remove_parameters"] = remove_kods

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

        product["variants"] = variants

        db_meta = {
            "id": prod_row["id"],
            "display_name": prod_row["display_name"],
            "spec_number": prod_row["spec_number"],
            "cas_number": prod_row["cas_number"],
            "expiry_months": prod_row["expiry_months"],
            "opinion_pl": prod_row["opinion_pl"],
            "opinion_en": prod_row["opinion_en"],
        }

    return jsonify({"ok": True, "product": product, "db_meta": db_meta})


@certs_bp.route("/api/cert/config/product/<key>", methods=["PUT"])
@role_required("admin")
def api_cert_config_product_put(key):
    """Save product parameters + variants to DB, regenerate JSON export."""
    from mbr.certs.generator import save_cert_config_export

    data = request.get_json(silent=True) or {}
    parameters = data.get("parameters")
    variants = data.get("variants")

    with db_session() as db:
        # Check product exists and has cert config
        prod_row = db.execute("SELECT id FROM produkty WHERE nazwa = ?", (key,)).fetchone()
        if not prod_row:
            return jsonify({"error": "Product not found"}), 404
        has_variants = db.execute("SELECT 1 FROM cert_variants WHERE produkt = ? LIMIT 1", (key,)).fetchone()
        if not has_variants:
            return jsonify({"error": "Product not found"}), 404

        # Build kod_to_id lookup from parametry_analityczne
        pa_rows = db.execute("SELECT id, kod FROM parametry_analityczne").fetchall()
        kod_to_id = {r["kod"]: r["id"] for r in pa_rows if r["kod"]}

        # Whitelist: only kody present in the active MBR's analiza_koncowa may be
        # used on the certificate. If there's no active MBR, reject any attempt
        # to add parameters to the cert (user must create/activate the MBR first).
        from mbr.technolog.models import get_active_mbr
        mbr = get_active_mbr(db, key)
        analiza_kody = set()
        if mbr:
            try:
                plab = _json.loads(mbr.get("parametry_lab") or "{}")
            except Exception:
                plab = {}
            pola = ((plab.get("analiza_koncowa") or {}).get("pola")) or []
            analiza_kody = {p.get("kod") for p in pola if p.get("kod")}

        def _reject_if_not_in_analiza(df: str, context: str):
            if not df:
                return None
            if not mbr:
                return jsonify({"error": f"{context}: brak aktywnego MBR dla produktu „{key}” — nie można przypisać parametru „{df}”"}), 400
            if df not in analiza_kody:
                return jsonify({"error": f"{context}: parametr „{df}” nie występuje w sekcji „analiza końcowa” aktywnego MBR"}), 400
            return None

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
                if not p.get("name_pl"):
                    return jsonify({"error": f"Parameter '{pid}' missing name_pl"}), 400
                df = (p.get("data_field") or "").strip()
                if df and df not in kod_to_id:
                    return jsonify({"error": f"Parameter '{pid}': data_field '{df}' not found in parametry_analityczne"}), 400
                err = _reject_if_not_in_analiza(df, f"Parametr „{pid}”")
                if err:
                    return err

        # Validate variants
        if variants is not None:
            base_param_ids = {p.get("id", "").strip() for p in (parameters or [])} if parameters is not None else set()
            if not base_param_ids and parameters is None:
                # Load existing base param ids from DB
                existing_base = db.execute(
                    "SELECT pa.kod FROM parametry_cert pc JOIN parametry_analityczne pa ON pa.id=pc.parametr_id "
                    "WHERE pc.produkt=? AND pc.variant_id IS NULL", (key,)
                ).fetchall()
                base_param_ids = {r["kod"] for r in existing_base if r["kod"]}

            variant_ids = set()
            for v in variants:
                vid = v.get("id", "").strip()
                if not vid:
                    return jsonify({"error": "Variant missing id"}), 400
                if vid in variant_ids:
                    return jsonify({"error": f"Duplicate variant id: {vid}"}), 400
                variant_ids.add(vid)
                if not v.get("label"):
                    return jsonify({"error": f"Variant '{vid}' missing label"}), 400
                overrides = v.get("overrides") or {}
                remove_params = overrides.get("remove_parameters", [])
                for rp in remove_params:
                    if rp not in base_param_ids:
                        return jsonify({"error": f"Variant '{vid}' remove_parameters references unknown param: {rp}"}), 400
                for ap in overrides.get("add_parameters", []) or []:
                    ap_df = (ap.get("data_field") or ap.get("id") or "").strip()
                    err = _reject_if_not_in_analiza(ap_df, f"Wariant „{vid}”, parametr „{ap_df}”")
                    if err:
                        return err

        # Update produkty metadata
        for field in ("display_name", "spec_number", "cas_number", "expiry_months", "opinion_pl", "opinion_en"):
            if field in data:
                db.execute(f"UPDATE produkty SET {field} = ? WHERE nazwa = ?", (data[field], key))

        # Replace base parameters (variant_id IS NULL)
        if parameters is not None:
            db.execute("DELETE FROM parametry_cert WHERE produkt = ? AND variant_id IS NULL", (key,))
            for idx, p in enumerate(parameters):
                df = (p.get("data_field") or p.get("id", "")).strip()
                parametr_id = kod_to_id.get(df)
                if not parametr_id:
                    continue  # skip params without valid analityczne mapping
                db.execute(
                    "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, qualitative_result, name_pl, name_en, method, variant_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                    (key, parametr_id, idx, p.get("requirement", ""), p.get("format", "1"),
                     p.get("qualitative_result") or None,
                     p.get("name_pl") or None, p.get("name_en") or None, p.get("method") or None),
                )

        # Replace variants
        if variants is not None:
            # Delete old variant add_params first (foreign key)
            old_variant_rows = db.execute("SELECT id FROM cert_variants WHERE produkt=?", (key,)).fetchall()
            for ovr in old_variant_rows:
                db.execute("DELETE FROM parametry_cert WHERE variant_id = ?", (ovr["id"],))
            db.execute("DELETE FROM cert_variants WHERE produkt = ?", (key,))

            for idx, v in enumerate(variants):
                overrides = v.get("overrides") or {}
                # Convert remove_parameters (string kod array) to integer parametr_id array
                remove_kods = overrides.get("remove_parameters", [])
                remove_ids = [kod_to_id[k] for k in remove_kods if k in kod_to_id]

                cur = db.execute(
                    "INSERT INTO cert_variants (produkt, variant_id, label, flags, spec_number, opinion_pl, opinion_en, avon_code, avon_name, remove_params, kolejnosc) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (key, v.get("id", ""), v.get("label", ""),
                     _json.dumps(v.get("flags", []), ensure_ascii=False),
                     overrides.get("spec_number") or None,
                     overrides.get("opinion_pl") or None,
                     overrides.get("opinion_en") or None,
                     overrides.get("avon_code") or None,
                     overrides.get("avon_name") or None,
                     _json.dumps(remove_ids), idx),
                )
                new_cv_id = cur.lastrowid

                # Insert variant add_parameters
                add_params = overrides.get("add_parameters", [])
                for ap_idx, ap in enumerate(add_params):
                    ap_df = (ap.get("data_field") or ap.get("id", "")).strip()
                    ap_parametr_id = kod_to_id.get(ap_df)
                    if not ap_parametr_id:
                        continue
                    db.execute(
                        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, qualitative_result, name_pl, name_en, method, variant_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (key, ap_parametr_id, ap_idx, ap.get("requirement", ""), ap.get("format", "1"),
                         ap.get("qualitative_result") or None,
                         ap.get("name_pl") or None, ap.get("name_en") or None, ap.get("method") or None,
                         new_cv_id),
                    )

        db.commit()
        save_cert_config_export(db)

    return jsonify({"ok": True})


@certs_bp.route("/api/cert/config/product", methods=["POST"])
@role_required("admin")
def api_cert_config_product_create():
    """Create a new product with cert config in DB."""
    import re
    from mbr.certs.generator import save_cert_config_export

    data = request.get_json(silent=True) or {}
    display_name = (data.get("display_name") or "").strip()
    if not display_name:
        return jsonify({"error": "display_name is required"}), 400

    key = display_name.replace(" ", "_")
    if not re.match(r'^[A-Za-z0-9_\-]+$', key):
        return jsonify({"error": "Nazwa zawiera niedozwolone znaki (dozwolone: litery, cyfry, _, -)"}), 400

    with db_session() as db:
        # Check if cert config already exists
        existing_cv = db.execute("SELECT 1 FROM cert_variants WHERE produkt = ? LIMIT 1", (key,)).fetchone()
        if existing_cv:
            return jsonify({"error": f"Product '{key}' already exists"}), 409

        # Insert into produkty if not exists
        existing_prod = db.execute("SELECT id FROM produkty WHERE nazwa = ?", (key,)).fetchone()
        if not existing_prod:
            db.execute(
                "INSERT INTO produkty (nazwa, display_name, spec_number, cas_number, expiry_months, opinion_pl, opinion_en) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key, display_name, data.get("spec_number", ""), data.get("cas_number", ""),
                 data.get("expiry_months", 12), data.get("opinion_pl", ""), data.get("opinion_en", "")),
            )

        # Insert default "base" variant
        db.execute(
            "INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
            "VALUES (?, 'base', ?, '[]', 0)",
            (key, display_name),
        )

        db.commit()
        save_cert_config_export(db)

    return jsonify({"ok": True, "key": key})


@certs_bp.route("/api/cert/config/product/<key>", methods=["DELETE"])
@role_required("admin")
def api_cert_config_product_delete(key):
    """Delete a product's cert config from DB."""
    from mbr.certs.generator import save_cert_config_export

    with db_session() as db:
        has_variants = db.execute("SELECT 1 FROM cert_variants WHERE produkt = ? LIMIT 1", (key,)).fetchone()
        if not has_variants:
            return jsonify({"error": "Product not found"}), 404

        # Check for issued certificates
        warning = None
        prod_row = db.execute("SELECT display_name FROM produkty WHERE nazwa = ?", (key,)).fetchone()
        display_name = prod_row["display_name"] if prod_row else key
        row = db.execute(
            "SELECT COUNT(*) as cnt FROM swiadectwa WHERE template_name LIKE ?",
            (f"{display_name}%",),
        ).fetchone()
        if row and row["cnt"] > 0:
            warning = f"Istnieje {row['cnt']} wydanych świadectw dla tego produktu. Dane archiwalne pozostają nienaruszone."

        # Delete: variant add_params → cert_variants → base parametry_cert
        variant_rows = db.execute("SELECT id FROM cert_variants WHERE produkt=?", (key,)).fetchall()
        for vr in variant_rows:
            db.execute("DELETE FROM parametry_cert WHERE variant_id = ?", (vr["id"],))
        db.execute("DELETE FROM cert_variants WHERE produkt = ?", (key,))
        db.execute("DELETE FROM parametry_cert WHERE produkt = ? AND variant_id IS NULL", (key,))

        db.commit()
        save_cert_config_export(db)

    result = {"ok": True}
    if warning:
        result["warning"] = warning
    return jsonify(result)


@certs_bp.route("/api/cert/config/export")
@role_required("admin")
def api_cert_config_export():
    """Export cert config from DB, regenerate JSON file, and return it."""
    with db_session() as db:
        from mbr.certs.generator import save_cert_config_export, export_cert_config
        save_cert_config_export(db)
        cfg = export_cert_config(db)
    return jsonify(cfg)


@certs_bp.route("/api/cert/config/preview", methods=["POST"])
@role_required("admin")
def api_cert_config_preview():
    """Generate a live PDF preview from editor JSON payload (no DB)."""
    data = request.get_json(silent=True) or {}
    product = data.get("product")
    variant_id = data.get("variant_id", "base")

    if not product:
        return jsonify({"error": "Missing 'product' in request body"}), 400

    try:
        ctx = build_preview_context(product, variant_id)
        docx_bytes = _docxtpl_render(ctx)
        pdf_bytes = _gotenberg_convert(docx_bytes)
        return Response(pdf_bytes, mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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


@certs_bp.route("/api/cert/<int:cert_id>/audit-history")
@role_required("admin", "technolog", "cert", "lab")
def cert_audit_history(cert_id):
    """Return per-cert audit history (sorted DESC by dt, with actors)."""
    from mbr.shared import audit
    with db_session() as db:
        history = audit.query_audit_history_for_entity(db, "cert", cert_id)
    return jsonify({"history": history})


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
