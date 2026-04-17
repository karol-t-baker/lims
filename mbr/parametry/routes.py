import json as _json

from flask import request, jsonify, render_template, session

from mbr.parametry import parametry_bp
from mbr.parametry.registry import get_parametry_for_kontekst, get_calc_methods, get_konteksty, build_parametry_lab
from mbr.shared.decorators import login_required, role_required
from mbr.db import db_session


def _find_pipeline_etap_id(db, produkt, kontekst, pipeline):
    """Map kontekst to pipeline etap_id."""
    cykliczne = [s for s in pipeline if s["typ_cyklu"] == "cykliczny"]
    main_cykliczny_id = cykliczne[-1]["etap_id"] if cykliczne else None
    for step in pipeline:
        if step["typ_cyklu"] == "cykliczny" and step["etap_id"] == main_cykliczny_id:
            if kontekst in ("analiza_koncowa", "analiza"):
                return step["etap_id"]
        elif step["kod"] == kontekst:
            return step["etap_id"]
    return None


@parametry_bp.route("/api/parametry/config")
@login_required
def api_parametry_config():
    """Universal parameter config endpoint."""
    produkt = request.args.get("produkt", "")
    kontekst = request.args.get("kontekst", "")
    if not kontekst:
        return jsonify({"error": "kontekst is required"}), 400
    with db_session() as db:
        params = get_parametry_for_kontekst(db, produkt, kontekst)
    return jsonify(params)


@parametry_bp.route("/api/parametry/calc-methods")
@login_required
def api_calc_methods():
    """Titration calc methods for calculator.js."""
    with db_session() as db:
        methods = get_calc_methods(db)
    return jsonify(methods)


@parametry_bp.route("/api/parametry/list")
@login_required
def api_parametry_list():
    """All parameters with their etapy bindings. Admin sees inactive too."""
    rola = session.get("user", {}).get("rola", "")
    where = "" if rola == "admin" else "WHERE aktywny=1"
    with db_session() as db:
        params = db.execute(
            f"SELECT * FROM parametry_analityczne {where} ORDER BY typ, kod"
        ).fetchall()
        result = []
        for p in params:
            d = dict(p)
            bindings = db.execute(
                "SELECT * FROM parametry_etapy WHERE parametr_id=? ORDER BY kontekst, produkt",
                (p["id"],),
            ).fetchall()
            d["bindings"] = [dict(b) for b in bindings]
            result.append(d)
    return jsonify(result)


@parametry_bp.route("/api/parametry/<int:param_id>", methods=["PUT"])
@login_required
def api_parametry_update(param_id):
    """Update global parameter fields. Admin can edit additional fields."""
    data = request.get_json(silent=True) or {}
    rola = session.get("user", {}).get("rola", "")
    allowed = {"label", "skrot", "formula", "metoda_nazwa", "metoda_formula", "metoda_factor", "precision"}
    if rola == "admin":
        allowed |= {"typ", "jednostka", "aktywny", "name_en", "method_code"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields"}), 400
    sets = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [param_id]
    with db_session() as db:
        db.execute(f"UPDATE parametry_analityczne SET {sets} WHERE id=?", vals)
        # Rebuild parametry_lab for all active templates that use this parameter
        affected = db.execute(
            """SELECT DISTINCT mt.produkt
               FROM mbr_templates mt
               JOIN parametry_etapy pe ON pe.produkt = mt.produkt
               WHERE pe.parametr_id = ? AND mt.status = 'active'""",
            (param_id,),
        ).fetchall()
        for row in affected:
            plab = build_parametry_lab(db, row["produkt"])
            db.execute(
                "UPDATE mbr_templates SET parametry_lab=? WHERE produkt=? AND status='active'",
                (_json.dumps(plab, ensure_ascii=False), row["produkt"]),
            )
        db.commit()
    return jsonify({"ok": True})


@parametry_bp.route("/api/parametry", methods=["POST"])
@role_required("admin")
def api_parametry_create():
    """Create a new analytical parameter (admin only)."""
    data = request.get_json(silent=True) or {}
    kod = (data.get("kod") or "").strip()
    label = (data.get("label") or "").strip()
    typ = data.get("typ", "bezposredni")
    if not kod or not label:
        return jsonify({"error": "kod and label required"}), 400
    with db_session() as db:
        try:
            cur = db.execute(
                "INSERT INTO parametry_analityczne (kod, label, skrot, typ, jednostka, precision, name_en, method_code) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (kod, label, data.get("skrot", ""), typ, data.get("jednostka", ""),
                 data.get("precision", 2), data.get("name_en", ""), data.get("method_code", "")),
            )
            db.commit()
        except Exception:
            return jsonify({"error": "Parametr already exists"}), 409
    return jsonify({"ok": True, "id": cur.lastrowid})


@parametry_bp.route("/api/parametry/etapy", methods=["POST"])
@login_required
def api_parametry_etapy_create():
    """Create new binding. For pipeline products, creates in produkt_etap_limity + etap_parametry."""
    data = request.get_json(silent=True) or {}
    parametr_id = data.get("parametr_id")
    kontekst = data.get("kontekst", "")
    produkt = data.get("produkt") or None
    nawazka = data.get("nawazka_g")
    mn = data.get("min_limit")
    mx = data.get("max_limit")
    if not parametr_id or not kontekst:
        return jsonify({"error": "parametr_id and kontekst required"}), 400

    with db_session() as db:
        # Check if product has pipeline
        if produkt:
            from mbr.pipeline.models import get_produkt_pipeline, set_produkt_etap_limit, add_etap_parametr
            pipeline = get_produkt_pipeline(db, produkt)
            if pipeline:
                etap_id = _find_pipeline_etap_id(db, produkt, kontekst, pipeline)
                if etap_id:
                    # Ensure param exists in global etap_parametry
                    existing_ep = db.execute(
                        "SELECT id FROM etap_parametry WHERE etap_id=? AND parametr_id=?",
                        (etap_id, parametr_id),
                    ).fetchone()
                    max_kol = db.execute(
                        "SELECT MAX(kolejnosc) FROM etap_parametry WHERE etap_id=?",
                        (etap_id,),
                    ).fetchone()[0] or 0
                    if not existing_ep:
                        add_etap_parametr(db, etap_id, parametr_id, kolejnosc=max_kol + 1)
                    # Set product limit
                    set_produkt_etap_limit(db, produkt, etap_id, parametr_id,
                                          min_limit=mn, max_limit=mx, nawazka_g=nawazka)
                    pel = db.execute(
                        "SELECT id FROM produkt_etap_limity WHERE produkt=? AND etap_id=? AND parametr_id=?",
                        (produkt, etap_id, parametr_id),
                    ).fetchone()
                    db.commit()
                    return jsonify({"ok": True, "id": pel["id"] if pel else 0})

        # Legacy path
        existing = db.execute(
            "SELECT id FROM parametry_etapy WHERE parametr_id=? AND kontekst=? AND produkt IS ?",
            (parametr_id, kontekst, produkt),
        ).fetchone()
        if existing:
            return jsonify({"error": "Duplicate binding"}), 409
        grupa = data.get("grupa", "lab")
        cur = db.execute(
            """INSERT INTO parametry_etapy (parametr_id, kontekst, produkt, nawazka_g, min_limit, max_limit, grupa)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (parametr_id, kontekst, produkt, nawazka, mn, mx, grupa),
        )
        db.commit()
        new_id = cur.lastrowid
    return jsonify({"ok": True, "id": new_id})


@parametry_bp.route("/api/parametry/etapy/<int:binding_id>", methods=["PUT"])
@login_required
def api_parametry_etapy_update(binding_id):
    """Update binding fields. Works for both parametry_etapy and produkt_etap_limity."""
    data = request.get_json(silent=True) or {}

    with db_session() as db:
        # Check if this binding_id belongs to produkt_etap_limity (pipeline)
        pel_row = db.execute(
            "SELECT id FROM produkt_etap_limity WHERE id=?", (binding_id,)
        ).fetchone()

        if pel_row:
            # Pipeline mode: update produkt_etap_limity
            # Frontend sends "target" but column is now "spec_value"
            if "target" in data and "spec_value" not in data:
                data["spec_value"] = data.pop("target")
            allowed = {"nawazka_g", "min_limit", "max_limit", "spec_value", "precision"}
            updates = {k: v for k, v in data.items() if k in allowed}
            if not updates:
                return jsonify({"error": "No valid fields"}), 400
            # For limit fields, store '' (empty string) instead of NULL
            # to distinguish "explicitly no limit" from "no override".
            for lf in ("min_limit", "max_limit"):
                if lf in updates and updates[lf] is None:
                    updates[lf] = ''
            sets = ", ".join(f"{k}=?" for k in updates)
            vals = list(updates.values()) + [binding_id]
            db.execute(f"UPDATE produkt_etap_limity SET {sets} WHERE id=?", vals)
            db.commit()
            return jsonify({"ok": True})

        # Legacy mode: update parametry_etapy
        allowed = {"nawazka_g", "min_limit", "max_limit", "target", "kolejnosc", "formula", "sa_bias", "precision", "grupa"}
        updates = {k: v for k, v in data.items() if k in allowed}
        if not updates:
            return jsonify({"error": "No valid fields"}), 400
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [binding_id]
        db.execute(f"UPDATE parametry_etapy SET {sets} WHERE id=?", vals)
        row = db.execute(
            "SELECT produkt FROM parametry_etapy WHERE id=?", (binding_id,)
        ).fetchone()
        if row and row["produkt"]:
            plab = build_parametry_lab(db, row["produkt"])
            db.execute(
                "UPDATE mbr_templates SET parametry_lab=? WHERE produkt=? AND status='active'",
                (_json.dumps(plab, ensure_ascii=False), row["produkt"]),
            )
        db.commit()
    return jsonify({"ok": True})


@parametry_bp.route("/api/parametry/sa-bias", methods=["PUT"])
@login_required
def api_parametry_sa_bias():
    """Update sa_bias for a product's binding. Body: {kod, produkt, sa_bias}"""
    data = request.get_json(silent=True) or {}
    kod = data.get("kod", "sa")
    produkt = data.get("produkt", "")
    sa_bias = data.get("sa_bias")
    if sa_bias is None:
        return jsonify({"error": "sa_bias required"}), 400
    with db_session() as db:
        # Find binding for this product + kod in analiza_koncowa
        row = db.execute(
            """SELECT pe.id, pa.formula AS global_formula FROM parametry_etapy pe
               JOIN parametry_analityczne pa ON pe.parametr_id = pa.id
               WHERE pa.kod = ? AND pe.produkt = ? AND pe.kontekst = 'analiza_koncowa'""",
            (kod, produkt),
        ).fetchone()
        if not row:
            # Try default (NULL produkt)
            row = db.execute(
                """SELECT pe.id, pa.formula AS global_formula FROM parametry_etapy pe
                   JOIN parametry_analityczne pa ON pe.parametr_id = pa.id
                   WHERE pa.kod = ? AND pe.produkt IS NULL AND pe.kontekst = 'analiza_koncowa'""",
                (kod,),
            ).fetchone()
        if not row:
            return jsonify({"error": "Binding not found"}), 404

        # If global formula uses 'sa_bias' placeholder, updating sa_bias field is enough —
        # get_parametry_for_kontekst substitutes it automatically.
        # If global formula has a hardcoded number, embed the new value in binding_formula.
        import re as _re
        global_formula = row["global_formula"] or ""
        if "sa_bias" in global_formula:
            # Placeholder-based: just update sa_bias, no binding formula needed
            db.execute(
                "UPDATE parametry_etapy SET sa_bias=?, formula=NULL WHERE id=?",
                (sa_bias, row["id"]),
            )
        else:
            # Hardcoded number: replace trailing number with new bias in binding formula
            base = _re.sub(r'\s*[-+]\s*[\d.]+\s*$', '', global_formula).strip()
            new_formula = f"{base} - {sa_bias}" if base else None
            db.execute(
                "UPDATE parametry_etapy SET sa_bias=?, formula=? WHERE id=?",
                (sa_bias, new_formula, row["id"]),
            )
        # Mirror sa_bias to etap_parametry (pipeline reads from this table)
        pa_row = db.execute(
            "SELECT id FROM parametry_analityczne WHERE kod = ?", (kod,)
        ).fetchone()
        if pa_row:
            db.execute(
                "UPDATE etap_parametry SET sa_bias = ? WHERE parametr_id = ?",
                (sa_bias, pa_row["id"]),
            )

        # Rebuild parametry_lab snapshot so future form loads see the updated formula
        plab = build_parametry_lab(db, produkt)
        db.execute(
            "UPDATE mbr_templates SET parametry_lab=? WHERE produkt=? AND status='active'",
            (_json.dumps(plab, ensure_ascii=False), produkt),
        )
        db.commit()
    return jsonify({"ok": True})


@parametry_bp.route("/api/parametry/etapy/<int:binding_id>", methods=["DELETE"])
@login_required
def api_parametry_etapy_delete(binding_id):
    """Delete a binding. Works for both parametry_etapy and produkt_etap_limity."""
    with db_session() as db:
        pel = db.execute("SELECT id FROM produkt_etap_limity WHERE id=?", (binding_id,)).fetchone()
        if pel:
            db.execute("DELETE FROM produkt_etap_limity WHERE id=?", (binding_id,))
        else:
            db.execute("DELETE FROM parametry_etapy WHERE id=?", (binding_id,))
        db.commit()
    return jsonify({"ok": True})


@parametry_bp.route("/api/parametry/available")
@login_required
def api_parametry_available():
    """Active parameters for picker.

    If `?produkt=X` is given, restrict to parameters defined in the active MBR's
    `analiza_koncowa` section for that product. This enforces that certificate
    parameters can only be drawn from what the laborant actually measures.
    """
    produkt = (request.args.get("produkt") or "").strip()
    with db_session() as db:
        if produkt:
            from mbr.technolog.models import get_active_mbr
            mbr = get_active_mbr(db, produkt)
            if not mbr:
                return jsonify({"no_mbr": True, "produkt": produkt, "params": []})
            try:
                plab = _json.loads(mbr.get("parametry_lab") or "{}")
            except Exception:
                plab = {}
            allowed_kody = []
            for sekcja in plab.values():
                for p in (sekcja.get("pola") or []):
                    kod = p.get("kod")
                    if kod and kod not in allowed_kody:
                        allowed_kody.append(kod)
            if not allowed_kody:
                return jsonify({"no_mbr": True, "produkt": produkt, "params": []})
            placeholders = ",".join("?" * len(allowed_kody))
            rows = db.execute(
                f"SELECT id, kod, label, skrot, typ, name_en, method_code, precision "
                f"FROM parametry_analityczne WHERE aktywny=1 AND kod IN ({placeholders}) "
                f"ORDER BY typ, kod",
                allowed_kody,
            ).fetchall()
            return jsonify({"no_mbr": False, "produkt": produkt, "params": [dict(r) for r in rows]})
        rows = db.execute(
            "SELECT id, kod, label, skrot, typ, name_en, method_code, precision "
            "FROM parametry_analityczne WHERE aktywny=1 ORDER BY typ, kod"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@parametry_bp.route("/api/parametry/etapy/<produkt>/<kontekst>")
@login_required
def api_parametry_etapy_list(produkt, kontekst):
    """List raw etapy bindings for product+kontekst, with parameter info.

    For pipeline products, reads from produkt_etap_limity + etap_parametry
    instead of parametry_etapy, returning the same format.
    """
    with db_session() as db:
        from mbr.pipeline.models import get_produkt_pipeline
        pipeline = get_produkt_pipeline(db, produkt)
        if pipeline:
            return _list_pipeline_bindings(db, produkt, kontekst, pipeline)

        rows = db.execute(
            "SELECT pe.id, pe.parametr_id, pe.produkt, pe.kontekst, pe.min_limit, pe.max_limit, "
            "pe.target, pe.nawazka_g, pe.kolejnosc, pe.formula, pe.sa_bias, pe.precision, pe.grupa, "
            "pa.kod, pa.label, pa.skrot, pa.typ "
            "FROM parametry_etapy pe "
            "JOIN parametry_analityczne pa ON pa.id = pe.parametr_id "
            "WHERE (pe.produkt = ? OR pe.produkt IS NULL) AND pe.kontekst = ? "
            "ORDER BY pe.kolejnosc, pa.kod",
            (produkt, kontekst),
        ).fetchall()
    return jsonify([dict(r) for r in rows])


def _list_pipeline_bindings(db, produkt, kontekst, pipeline):
    """Return pipeline bindings in the same format as parametry_etapy rows."""
    from mbr.pipeline.models import resolve_limity

    # Map kontekst to pipeline etap_id
    # "analiza_koncowa" or "analiza" → find the matching stage
    etap_id = None
    cykliczne = [s for s in pipeline if s["typ_cyklu"] == "cykliczny"]
    main_cykliczny_id = cykliczne[-1]["etap_id"] if cykliczne else None

    for step in pipeline:
        if step["typ_cyklu"] == "cykliczny" and step["etap_id"] == main_cykliczny_id:
            if kontekst in ("analiza_koncowa", "analiza"):
                etap_id = step["etap_id"]
                break
        elif step["kod"] == kontekst:
            etap_id = step["etap_id"]
            break

    if etap_id is None:
        return jsonify([])

    resolved = resolve_limity(db, produkt, etap_id)
    # Filter to product-specific params
    product_param_ids = {r[0] for r in db.execute(
        "SELECT parametr_id FROM produkt_etap_limity WHERE produkt = ? AND etap_id = ?",
        (produkt, etap_id),
    ).fetchall()}

    result = []
    for r in resolved:
        if product_param_ids and r["parametr_id"] not in product_param_ids:
            continue
        # Use produkt_etap_limity.id as binding id (prefixed to avoid collision)
        pel_row = db.execute(
            "SELECT id FROM produkt_etap_limity WHERE produkt=? AND etap_id=? AND parametr_id=?",
            (produkt, etap_id, r["parametr_id"]),
        ).fetchone()
        binding_id = pel_row["id"] if pel_row else r["ep_id"]

        result.append({
            "id": binding_id,
            "parametr_id": r["parametr_id"],
            "produkt": produkt,
            "kontekst": kontekst,
            "min_limit": r["min_limit"],
            "max_limit": r["max_limit"],
            "target": r.get("spec_value") or r.get("target"),
            "nawazka_g": r["nawazka_g"],
            "kolejnosc": r["kolejnosc"],
            "formula": r["formula"],
            "sa_bias": r["sa_bias"],
            "precision": r["precision"],
            "grupa": r["grupa"],
            "kod": r["kod"],
            "label": r["label"],
            "skrot": r["skrot"],
            "typ": r["typ"],
            "_pipeline": True,
            "_etap_id": etap_id,
        })
    return jsonify(result)


@parametry_bp.route("/api/parametry/etapy/reorder", methods=["POST"])
@login_required
def api_parametry_etapy_reorder():
    """Batch-update kolejnosc for multiple bindings. Body: {bindings: [{id, kolejnosc}, ...]}"""
    data = request.get_json(silent=True) or {}
    bindings = data.get("bindings", [])
    if not bindings:
        return jsonify({"error": "bindings required"}), 400
    with db_session() as db:
        for b in bindings:
            db.execute("UPDATE parametry_etapy SET kolejnosc=? WHERE id=?", (b["kolejnosc"], b["id"]))
        db.commit()
    return jsonify({"ok": True})


@parametry_bp.route("/api/parametry/rebuild-mbr", methods=["POST"])
@login_required
def api_rebuild_mbr():
    """Rebuild parametry_lab JSON in active MBR for a product from parametry_etapy."""
    data = request.get_json(silent=True) or {}
    produkt = data.get("produkt", "")
    if not produkt:
        return jsonify({"ok": False, "error": "produkt required"}), 400
    with db_session() as db:
        plab = build_parametry_lab(db, produkt)
        plab_json = _json.dumps(plab, ensure_ascii=False)
        db.execute(
            "UPDATE mbr_templates SET parametry_lab=? WHERE produkt=? AND status='active'",
            (plab_json, produkt),
        )
        db.commit()
    return jsonify({"ok": True})


# ═══ PRODUKTY ═══

@parametry_bp.route("/api/produkty")
@login_required
def api_produkty():
    include_all = request.args.get("all") == "1"
    typ_filter = request.args.get("typ", "")
    with db_session() as db:
        sql = "SELECT * FROM produkty"
        params = []
        conditions = []
        if not include_all:
            conditions.append("aktywny = 1")
        if typ_filter:
            conditions.append("typy LIKE ?")
            params.append(f'%"{typ_filter}"%')
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY nazwa"
        rows = [dict(r) for r in db.execute(sql, params).fetchall()]
    return jsonify(rows)

@parametry_bp.route("/api/produkty", methods=["POST"])
@role_required("admin")
def api_produkty_create():
    data = request.get_json(silent=True) or {}
    nazwa = (data.get("nazwa") or "").strip()
    if not nazwa:
        return jsonify({"error": "nazwa required"}), 400
    display_name = data.get("display_name") or nazwa.replace("_", " ")
    with db_session() as db:
        try:
            cur = db.execute(
                "INSERT INTO produkty (nazwa, kod, display_name, typy, spec_number, "
                "cas_number, expiry_months, opinion_pl, opinion_en) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (nazwa, data.get("kod", ""), display_name,
                 data.get("typy", '["szarza"]'),
                 data.get("spec_number", ""), data.get("cas_number", ""),
                 data.get("expiry_months", 12),
                 data.get("opinion_pl", ""), data.get("opinion_en", "")),
            )
            db.commit()
        except Exception:
            return jsonify({"error": "Produkt already exists"}), 409
    return jsonify({"ok": True, "id": cur.lastrowid})

@parametry_bp.route("/api/produkty/<int:pid>", methods=["PUT"])
@role_required("admin")
def api_produkty_update(pid):
    data = request.get_json(silent=True) or {}
    allowed = {"kod", "display_name", "aktywny", "typy", "spec_number",
               "cas_number", "expiry_months", "opinion_pl", "opinion_en"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates:
        return jsonify({"ok": True})
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with db_session() as db:
        db.execute(f"UPDATE produkty SET {set_clause} WHERE id = ?",
                   [*updates.values(), pid])
        db.commit()
    return jsonify({"ok": True})

@parametry_bp.route("/api/produkty/<int:pid>", methods=["DELETE"])
@role_required("admin")
def api_produkty_delete(pid):
    with db_session() as db:
        db.execute("UPDATE produkty SET aktywny = 0 WHERE id = ?", (pid,))
        db.commit()
    return jsonify({"ok": True})


@parametry_bp.route("/parametry")
@role_required("admin", "technolog")
def parametry_editor():
    """Parameter editor page."""
    rola = session.get("user", {}).get("rola", "")
    with db_session() as db:
        products = [r["produkt"] for r in db.execute(
            "SELECT DISTINCT produkt FROM mbr_templates WHERE status='active' ORDER BY produkt"
        ).fetchall()]
        konteksty = get_konteksty(db)
    return render_template(
        "parametry_editor.html",
        products=products, konteksty=konteksty,
        is_admin=(rola == "admin"),
    )


# ============================================================================
# /api/bindings/* — new SSOT endpoints for produkt_etap_limity CRUD
# ============================================================================

@parametry_bp.route("/api/bindings")
@login_required
def api_bindings_list():
    """List bindings for a given (produkt, etap).

    Query args:
      produkt   — product kod (required)
      etap_id   — int, matches etapy_analityczne.id (either this OR etap_kod)
      etap_kod  — str, matches etapy_analityczne.kod

    Returns: JSON array of dicts with binding fields + joined parameter info.
    """
    produkt = request.args.get("produkt", "").strip()
    if not produkt:
        return jsonify({"error": "produkt is required"}), 400

    etap_id_str = request.args.get("etap_id")
    etap_kod = request.args.get("etap_kod", "").strip()

    with db_session() as db:
        if etap_id_str:
            try:
                etap_id = int(etap_id_str)
            except ValueError:
                return jsonify({"error": "etap_id must be integer"}), 400
        elif etap_kod:
            row = db.execute(
                "SELECT id FROM etapy_analityczne WHERE kod=?", (etap_kod,)
            ).fetchone()
            if not row:
                return jsonify({"error": f"unknown etap_kod: {etap_kod}"}), 404
            etap_id = row["id"]
        else:
            return jsonify({"error": "etap_id or etap_kod is required"}), 400

        rows = db.execute(
            """
            SELECT pel.id, pel.produkt, pel.etap_id, pel.parametr_id,
                   pel.min_limit, pel.max_limit, pel.precision, pel.nawazka_g,
                   pel.spec_value, pel.kolejnosc, pel.grupa, pel.formula,
                   pel.sa_bias, pel.krok, pel.wymagany,
                   pel.dla_szarzy, pel.dla_zbiornika, pel.dla_platkowania,
                   pa.kod, pa.label, pa.skrot, pa.typ, pa.jednostka
            FROM produkt_etap_limity pel
            JOIN parametry_analityczne pa ON pa.id = pel.parametr_id
            WHERE pel.produkt = ? AND pel.etap_id = ?
            ORDER BY pel.kolejnosc, pa.kod
            """,
            (produkt, etap_id),
        ).fetchall()

    return jsonify([dict(r) for r in rows])


_BINDING_FIELDS = {
    "min_limit", "max_limit", "precision", "nawazka_g", "spec_value",
    "kolejnosc", "grupa", "formula", "sa_bias", "krok", "wymagany",
    "dla_szarzy", "dla_zbiornika", "dla_platkowania",
}

_BINDING_DEFAULTS = {
    "kolejnosc": 0,
    "grupa": "lab",
    "wymagany": 0,
    "dla_szarzy": 1,
    "dla_zbiornika": 1,
    "dla_platkowania": 0,
}


@parametry_bp.route("/api/bindings", methods=["POST"])
@login_required
def api_bindings_create():
    """Create a new produkt_etap_limity binding.

    Accepts either `etap_id` (int) or `etap_kod` (str) — if `etap_kod` is given,
    resolve to `etap_id` via etapy_analityczne. The kod path lets callers without
    admin access (e.g. the laborant modal) avoid `/api/pipeline/etapy`.
    """
    import sqlite3 as _sqlite3
    data = request.get_json(silent=True) or {}
    produkt = (data.get("produkt") or "").strip()
    etap_id = data.get("etap_id")
    etap_kod = (data.get("etap_kod") or "").strip()
    parametr_id = data.get("parametr_id")
    if not produkt or not parametr_id:
        return jsonify({"error": "produkt and parametr_id are required"}), 400
    if not etap_id and not etap_kod:
        return jsonify({"error": "etap_id or etap_kod is required"}), 400

    row_fields = {k: data[k] for k in _BINDING_FIELDS if k in data}
    for k, v in _BINDING_DEFAULTS.items():
        row_fields.setdefault(k, v)

    with db_session() as db:
        if not etap_id:
            row = db.execute(
                "SELECT id FROM etapy_analityczne WHERE kod=?", (etap_kod,)
            ).fetchone()
            if not row:
                return jsonify({"error": f"unknown etap_kod: {etap_kod}"}), 404
            etap_id = row["id"]

        cols = ["produkt", "etap_id", "parametr_id"] + list(row_fields.keys())
        vals = [produkt, etap_id, parametr_id] + list(row_fields.values())
        placeholders = ", ".join("?" * len(cols))
        col_clause = ", ".join(cols)

        try:
            cur = db.execute(
                f"INSERT INTO produkt_etap_limity ({col_clause}) VALUES ({placeholders})",
                vals,
            )
            db.commit()
            return jsonify({"ok": True, "id": cur.lastrowid})
        except _sqlite3.IntegrityError as e:
            msg = str(e)
            if "UNIQUE" in msg:
                return jsonify({"error": "duplicate binding"}), 409
            return jsonify({"error": msg}), 400


@parametry_bp.route("/api/bindings/<int:binding_id>", methods=["PUT"])
@login_required
def api_bindings_update(binding_id: int):
    """Update a binding. If all three typ flags end up 0, auto-DELETE the row."""
    data = request.get_json(silent=True) or {}
    updates = {k: v for k, v in data.items() if k in _BINDING_FIELDS}
    if not updates:
        return jsonify({"error": "no valid fields to update"}), 400

    with db_session() as db:
        row = db.execute(
            "SELECT id FROM produkt_etap_limity WHERE id=?", (binding_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "binding not found"}), 404

        sets = ", ".join(f"{c}=?" for c in updates)
        vals = list(updates.values()) + [binding_id]
        db.execute(f"UPDATE produkt_etap_limity SET {sets} WHERE id=?", vals)

        post = db.execute(
            "SELECT dla_szarzy, dla_zbiornika, dla_platkowania "
            "FROM produkt_etap_limity WHERE id=?", (binding_id,)
        ).fetchone()
        auto_deleted = False
        if (post["dla_szarzy"] == 0 and post["dla_zbiornika"] == 0
                and post["dla_platkowania"] == 0):
            db.execute("DELETE FROM produkt_etap_limity WHERE id=?", (binding_id,))
            auto_deleted = True

        db.commit()

    return jsonify({"ok": True, "auto_deleted": auto_deleted})


@parametry_bp.route("/api/bindings/<int:binding_id>", methods=["DELETE"])
@login_required
def api_bindings_delete(binding_id: int):
    """Delete a binding."""
    with db_session() as db:
        row = db.execute(
            "SELECT id FROM produkt_etap_limity WHERE id=?", (binding_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "binding not found"}), 404
        db.execute("DELETE FROM produkt_etap_limity WHERE id=?", (binding_id,))
        db.commit()
    return jsonify({"ok": True})


@parametry_bp.route("/api/bindings/catalog")
@login_required
def api_bindings_catalog():
    """Active parametry_analityczne rows for picker UI."""
    with db_session() as db:
        rows = db.execute(
            "SELECT id, kod, label, skrot, typ, jednostka, precision, aktywny "
            "FROM parametry_analityczne "
            "WHERE aktywny=1 ORDER BY kod"
        ).fetchall()
    return jsonify([dict(r) for r in rows])
