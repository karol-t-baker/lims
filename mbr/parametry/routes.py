import json as _json

from flask import request, jsonify, render_template, session

from mbr.parametry import parametry_bp
from mbr.parametry.registry import get_parametry_for_kontekst, get_calc_methods, get_konteksty, build_parametry_lab
from mbr.shared.decorators import login_required, role_required
from mbr.db import db_session

ALLOWED_GRUPY = {"lab", "zewn"}


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
        allowed |= {"typ", "jednostka", "aktywny", "name_en", "method_code", "grupa", "opisowe_wartosci"}
    if "grupa" in data and data["grupa"] not in ALLOWED_GRUPY:
        return jsonify({"error": f"grupa must be one of: {', '.join(sorted(ALLOWED_GRUPY))}"}), 400

    with db_session() as db:
        existing = db.execute(
            "SELECT typ, kod, opisowe_wartosci FROM parametry_analityczne WHERE id=?",
            (param_id,),
        ).fetchone()
        if not existing:
            return jsonify({"error": "Parametr not found"}), 404

        if rola == "admin":
            # Determine effective typ after this update
            new_typ = data["typ"] if "typ" in data else existing["typ"]

            # Guard: block typ change if there are historical ebr_wyniki rows for this param.
            if "typ" in data and data["typ"] != existing["typ"]:
                historical = db.execute(
                    "SELECT 1 FROM ebr_wyniki WHERE kod_parametru=? LIMIT 1", (existing["kod"],)
                ).fetchone()
                if historical:
                    return jsonify({
                        "error": "Nie można zmienić typ parametru — istnieją historyczne wyniki. Admin musi je usunąć ręcznie."
                    }), 409

            # Validate opisowe_wartosci: JSON array of non-empty strings.
            opisowe_raw = data.get("opisowe_wartosci", "__UNSET__")
            if new_typ == "jakosciowy":
                if opisowe_raw == "__UNSET__":
                    if "typ" in data and data["typ"] == "jakosciowy" and existing["typ"] != "jakosciowy":
                        return jsonify({"error": "opisowe_wartosci is required when typ='jakosciowy'"}), 400
                else:
                    if not isinstance(opisowe_raw, list) or len(opisowe_raw) == 0:
                        return jsonify({"error": "opisowe_wartosci must be a non-empty list"}), 400
                    if not all(isinstance(v, str) and v.strip() for v in opisowe_raw):
                        return jsonify({"error": "opisowe_wartosci must be a list of non-empty strings"}), 400
            else:
                if opisowe_raw != "__UNSET__":
                    data.pop("opisowe_wartosci", None)
                    data["opisowe_wartosci"] = None
                if existing["typ"] == "jakosciowy" and new_typ != "jakosciowy":
                    data["opisowe_wartosci"] = None

            if "opisowe_wartosci" in data and isinstance(data["opisowe_wartosci"], list):
                data["opisowe_wartosci"] = _json.dumps(data["opisowe_wartosci"], ensure_ascii=False)

        updates = {k: v for k, v in data.items() if k in allowed}
        if not updates:
            return jsonify({"error": "No valid fields"}), 400
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [param_id]
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
    grupa = data.get("grupa", "lab")
    if not kod or not label:
        return jsonify({"error": "kod and label required"}), 400
    if grupa not in ALLOWED_GRUPY:
        return jsonify({"error": f"grupa must be one of: {', '.join(sorted(ALLOWED_GRUPY))}"}), 400
    with db_session() as db:
        try:
            cur = db.execute(
                "INSERT INTO parametry_analityczne (kod, label, skrot, typ, jednostka, precision, name_en, method_code, grupa) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kod, label, data.get("skrot", ""), typ, data.get("jednostka", ""),
                 data.get("precision", 2), data.get("name_en", ""), data.get("method_code", ""),
                 grupa),
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
                    # Resolve grupa: explicit body value → else inherit from parametry_analityczne → else 'lab'
                    if "grupa" in data:
                        grupa_val = data["grupa"]
                    else:
                        gr_row = db.execute(
                            "SELECT grupa FROM parametry_analityczne WHERE id=?", (parametr_id,)
                        ).fetchone()
                        grupa_val = (gr_row["grupa"] if gr_row and gr_row["grupa"] else "lab")
                    if grupa_val not in ALLOWED_GRUPY:
                        return jsonify({"error": f"grupa must be one of: {', '.join(sorted(ALLOWED_GRUPY))}"}), 400
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
                    # Set product limit — include grupa
                    set_produkt_etap_limit(db, produkt, etap_id, parametr_id,
                                          min_limit=mn, max_limit=mx, nawazka_g=nawazka,
                                          grupa=grupa_val)
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
        if "grupa" in data:
            grupa = data["grupa"]
        else:
            gr_row = db.execute(
                "SELECT grupa FROM parametry_analityczne WHERE id=?", (parametr_id,)
            ).fetchone()
            grupa = (gr_row["grupa"] if gr_row and gr_row["grupa"] else "lab")
        if grupa not in ALLOWED_GRUPY:
            return jsonify({"error": f"grupa must be one of: {', '.join(sorted(ALLOWED_GRUPY))}"}), 400
        cur = db.execute(
            """INSERT INTO parametry_etapy (parametr_id, kontekst, produkt, nawazka_g, min_limit, max_limit, grupa)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (parametr_id, kontekst, produkt, nawazka, mn, mx, grupa),
        )
        db.commit()
        new_id = cur.lastrowid
    return jsonify({"ok": True, "id": new_id})


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
            """SELECT pe.id, pa.formula AS global_formula, pa.id AS parametr_id
               FROM parametry_etapy pe
               JOIN parametry_analityczne pa ON pe.parametr_id = pa.id
               WHERE pa.kod = ? AND pe.produkt = ? AND pe.kontekst = 'analiza_koncowa'""",
            (kod, produkt),
        ).fetchone()
        is_global_fallback = False
        if not row:
            # No per-product binding — fall back to NULL-produkt (global) to
            # read the formula template, but DO NOT update the global row
            # (would leak to every other product sharing that binding).
            row = db.execute(
                """SELECT pe.id, pa.formula AS global_formula, pa.id AS parametr_id
                   FROM parametry_etapy pe
                   JOIN parametry_analityczne pa ON pe.parametr_id = pa.id
                   WHERE pa.kod = ? AND pe.produkt IS NULL AND pe.kontekst = 'analiza_koncowa'""",
                (kod,),
            ).fetchone()
            is_global_fallback = True
        if not row:
            return jsonify({"error": "Binding not found"}), 404

        # If global formula uses 'sa_bias' placeholder, updating sa_bias field is enough —
        # get_parametry_for_kontekst substitutes it automatically.
        # If global formula has a hardcoded number, embed the new value in binding_formula.
        import re as _re
        global_formula = row["global_formula"] or ""
        if "sa_bias" in global_formula:
            new_formula = None  # placeholder-based, no binding override needed
        else:
            base = _re.sub(r'\s*[-+]\s*[\d.]+\s*$', '', global_formula).strip()
            new_formula = f"{base} - {sa_bias}" if base else None

        if is_global_fallback:
            # Create a per-product binding instead of mutating the NULL-produkt
            # global row. The per-product row overrides the global in build_parametry_lab
            # / resolve_limity via produkt_etap_limity + parametry_etapy layering.
            db.execute(
                "INSERT INTO parametry_etapy (produkt, kontekst, parametr_id, sa_bias, formula) "
                "VALUES (?, 'analiza_koncowa', ?, ?, ?)",
                (produkt, row["parametr_id"], sa_bias, new_formula),
            )
        else:
            db.execute(
                "UPDATE parametry_etapy SET sa_bias=?, formula=? WHERE id=?",
                (sa_bias, new_formula, row["id"]),
            )
        # Mirror sa_bias to produkt_etap_limity for the SSOT pipeline read path.
        # Previously this wrote to etap_parametry.sa_bias (GLOBAL) which leaked
        # the value to every produkt. The per-produkt table (produkt_etap_limity)
        # is scoped by (produkt, etap_id, parametr_id) so nothing propagates.
        pa_row = db.execute(
            "SELECT id FROM parametry_analityczne WHERE kod = ?", (kod,)
        ).fetchone()
        if pa_row:
            parametr_id = pa_row["id"]
            # Locate the analiza_koncowa etap for this product's pipeline
            ak_etap = db.execute(
                "SELECT pp.etap_id FROM produkt_pipeline pp "
                "JOIN etapy_analityczne ea ON ea.id = pp.etap_id "
                "WHERE pp.produkt=? AND ea.kod='analiza_koncowa' LIMIT 1",
                (produkt,),
            ).fetchone()
            if ak_etap:
                etap_id_ak = ak_etap["etap_id"]
                exists = db.execute(
                    "SELECT id FROM produkt_etap_limity "
                    "WHERE produkt=? AND etap_id=? AND parametr_id=?",
                    (produkt, etap_id_ak, parametr_id),
                ).fetchone()
                if exists:
                    db.execute(
                        "UPDATE produkt_etap_limity SET sa_bias=? WHERE id=?",
                        (sa_bias, exists["id"]),
                    )
                else:
                    db.execute(
                        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, sa_bias) "
                        "VALUES (?, ?, ?, ?)",
                        (produkt, etap_id_ak, parametr_id, sa_bias),
                    )

        # Rebuild parametry_lab snapshot so future form loads see the updated formula
        plab = build_parametry_lab(db, produkt)
        db.execute(
            "UPDATE mbr_templates SET parametry_lab=? WHERE produkt=? AND status='active'",
            (_json.dumps(plab, ensure_ascii=False), produkt),
        )
        db.commit()
    return jsonify({"ok": True})


@parametry_bp.route("/api/parametry/available")
@login_required
def api_parametry_available():
    """Active parameters for picker — full registry with in_mbr flag.

    Without `?produkt=X`: returns legacy plain list of all active params.
    With `?produkt=X`: returns dict {no_mbr, produkt, params} where each
    param has `in_mbr: bool` indicating whether it's in the active MBR's
    analiza_koncowa for that product. The cert editor UI uses this to
    visually separate in-MBR params (mierzone przez laborantów) from
    outside-MBR (qualitative / external-lab) params.
    """
    produkt = (request.args.get("produkt") or "").strip()
    with db_session() as db:
        all_rows = db.execute(
            "SELECT id, kod, label, skrot, typ, name_en, method_code, precision "
            "FROM parametry_analityczne WHERE aktywny=1 ORDER BY typ, kod"
        ).fetchall()
        all_params = [dict(r) for r in all_rows]

        if not produkt:
            # Legacy shape for non-cert callers — plain list, no in_mbr flag.
            return jsonify(all_params)

        from mbr.technolog.models import get_active_mbr
        mbr = get_active_mbr(db, produkt)
        mbr_kody: set = set()
        if mbr:
            try:
                plab = _json.loads(mbr.get("parametry_lab") or "{}")
            except Exception:
                plab = {}
            for sekcja in plab.values():
                for p in (sekcja.get("pola") or []):
                    kod = p.get("kod")
                    if kod:
                        mbr_kody.add(kod)

        no_mbr = not bool(mbr_kody)
        for p in all_params:
            p["in_mbr"] = bool(p.get("kod") and p["kod"] in mbr_kody)

        return jsonify({"no_mbr": no_mbr, "produkt": produkt, "params": all_params})


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
    if "grupa" in data and data["grupa"] not in ALLOWED_GRUPY:
        return jsonify({"error": f"grupa must be one of: {', '.join(sorted(ALLOWED_GRUPY))}"}), 400

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
    if "grupa" in data and data["grupa"] not in ALLOWED_GRUPY:
        return jsonify({"error": f"grupa must be one of: {', '.join(sorted(ALLOWED_GRUPY))}"}), 400
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


@parametry_bp.route("/api/bindings/clear-stage", methods=["DELETE"])
@login_required
def api_bindings_clear_stage():
    """Delete all produkt_etap_limity rows for a (produkt, etap).

    Query: ?produkt=X&etap_id=Y OR ?produkt=X&etap_kod=Z
    Returns: {ok: true, deleted: N}
    """
    produkt = (request.args.get("produkt") or "").strip()
    if not produkt:
        return jsonify({"error": "produkt is required"}), 400
    etap_id_str = request.args.get("etap_id")
    etap_kod = (request.args.get("etap_kod") or "").strip()

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

        cur = db.execute(
            "DELETE FROM produkt_etap_limity WHERE produkt=? AND etap_id=?",
            (produkt, etap_id),
        )
        db.commit()
    return jsonify({"ok": True, "deleted": cur.rowcount})


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
