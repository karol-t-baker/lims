import json as _json

from flask import request, jsonify, render_template, session

from mbr.parametry import parametry_bp
from mbr.parametry.registry import get_parametry_for_kontekst, get_calc_methods, get_konteksty, build_parametry_lab
from mbr.shared.decorators import login_required, role_required
from mbr.db import db_session


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
    """Create new binding."""
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
        existing = db.execute(
            "SELECT id FROM parametry_etapy WHERE parametr_id=? AND kontekst=? AND produkt IS ?",
            (parametr_id, kontekst, produkt),
        ).fetchone()
        if existing:
            return jsonify({"error": "Duplicate binding"}), 409
        cur = db.execute(
            """INSERT INTO parametry_etapy (parametr_id, kontekst, produkt, nawazka_g, min_limit, max_limit)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (parametr_id, kontekst, produkt, nawazka, mn, mx),
        )
        db.commit()
        new_id = cur.lastrowid
    return jsonify({"ok": True, "id": new_id})


@parametry_bp.route("/api/parametry/etapy/<int:binding_id>", methods=["PUT"])
@login_required
def api_parametry_etapy_update(binding_id):
    """Update binding fields."""
    data = request.get_json(silent=True) or {}
    allowed = {"nawazka_g", "min_limit", "max_limit", "target", "kolejnosc", "formula", "sa_bias"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields"}), 400
    sets = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [binding_id]
    with db_session() as db:
        db.execute(f"UPDATE parametry_etapy SET {sets} WHERE id=?", vals)
        # Rebuild parametry_lab for the affected product
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
    """Delete a binding."""
    with db_session() as db:
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
            pola = ((plab.get("analiza_koncowa") or {}).get("pola")) or []
            allowed_kody = [p.get("kod") for p in pola if p.get("kod")]
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
    """List raw etapy bindings for product+kontekst, with parameter info."""
    with db_session() as db:
        rows = db.execute(
            "SELECT pe.*, pa.kod, pa.label, pa.skrot, pa.typ "
            "FROM parametry_etapy pe "
            "JOIN parametry_analityczne pa ON pa.id = pe.parametr_id "
            "WHERE (pe.produkt = ? OR pe.produkt IS NULL) AND pe.kontekst = ? "
            "ORDER BY pe.kolejnosc, pa.kod",
            (produkt, kontekst),
        ).fetchall()
    return jsonify([dict(r) for r in rows])


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


@parametry_bp.route("/api/parametry/cert/<produkt>")
@login_required
def api_parametry_cert_list(produkt):
    """List cert bindings for a product, JOINed with parametry_analityczne."""
    with db_session() as db:
        rows = db.execute(
            """SELECT pc.id, pc.produkt, pc.parametr_id, pc.kolejnosc,
                      pc.requirement, pc.format, pc.qualitative_result,
                      pa.kod, pa.label, pa.name_en, pa.method_code, pa.skrot
               FROM parametry_cert pc
               JOIN parametry_analityczne pa ON pc.parametr_id = pa.id
               WHERE pc.produkt = ?
               ORDER BY pc.kolejnosc""",
            (produkt,),
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@parametry_bp.route("/api/parametry/cert", methods=["POST"])
@role_required("admin")
def api_parametry_cert_create():
    """Create a cert binding."""
    data = request.get_json(silent=True) or {}
    produkt = data.get("produkt")
    parametr_id = data.get("parametr_id")
    if not produkt or not parametr_id:
        return jsonify({"error": "produkt and parametr_id required"}), 400
    kolejnosc = data.get("kolejnosc", 0)
    requirement = data.get("requirement")
    fmt = data.get("format")
    qualitative_result = data.get("qualitative_result")
    with db_session() as db:
        cur = db.execute(
            """INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, qualitative_result)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (produkt, parametr_id, kolejnosc, requirement, fmt, qualitative_result),
        )
        db.commit()
        new_id = cur.lastrowid
    return jsonify({"ok": True, "id": new_id})


@parametry_bp.route("/api/parametry/cert/<int:binding_id>", methods=["PUT"])
@role_required("admin")
def api_parametry_cert_update(binding_id):
    """Update cert binding fields."""
    data = request.get_json(silent=True) or {}
    allowed = {"kolejnosc", "requirement", "format", "qualitative_result"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields"}), 400
    sets = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [binding_id]
    with db_session() as db:
        db.execute(f"UPDATE parametry_cert SET {sets} WHERE id=?", vals)
        db.commit()
    return jsonify({"ok": True})


@parametry_bp.route("/api/parametry/cert/<int:binding_id>", methods=["DELETE"])
@role_required("admin")
def api_parametry_cert_delete(binding_id):
    """Delete a cert binding."""
    with db_session() as db:
        db.execute("DELETE FROM parametry_cert WHERE id=?", (binding_id,))
        db.commit()
    return jsonify({"ok": True})


@parametry_bp.route("/api/parametry/cert/reorder", methods=["POST"])
@role_required("admin")
def api_parametry_cert_reorder():
    """Batch-update kolejnosc for cert bindings. Body: {bindings: [{id, kolejnosc}, ...]}"""
    data = request.get_json(silent=True) or {}
    bindings = data.get("bindings", [])
    if not bindings:
        return jsonify({"error": "bindings required"}), 400
    with db_session() as db:
        for b in bindings:
            db.execute("UPDATE parametry_cert SET kolejnosc=? WHERE id=?", (b["kolejnosc"], b["id"]))
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
        cert_products = [r["produkt"] for r in db.execute(
            "SELECT DISTINCT produkt FROM parametry_cert ORDER BY produkt"
        ).fetchall()]
        all_products = sorted(set(products) | set(cert_products))
    return render_template(
        "parametry_editor.html",
        products=products, konteksty=konteksty,
        is_admin=(rola == "admin"),
        cert_products=all_products,
    )
