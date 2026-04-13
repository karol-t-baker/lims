"""
pipeline/lab_routes.py — Laborant-facing REST API routes for fast entry v2.

All routes require login_required (any authenticated user).
DB access via get_db().
"""

from flask import jsonify, request, session

from mbr.pipeline import pipeline_bp
from mbr.db import get_db
from mbr.pipeline import models as pm
from mbr.shared.decorators import login_required


# ---------------------------------------------------------------------------
# GET /api/pipeline/lab/ebr/<ebr_id>/pipeline
# Enriched product pipeline with per-stage session status.
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/pipeline", methods=["GET"])
@login_required
def lab_get_pipeline(ebr_id):
    db = get_db()
    try:
        # Resolve ebr → mbr_templates → produkt
        ebr = db.execute(
            """SELECT e.ebr_id, m.produkt
               FROM ebr_batches e
               JOIN mbr_templates m ON m.mbr_id = e.mbr_id
               WHERE e.ebr_id = ?""",
            (ebr_id,),
        ).fetchone()
        if ebr is None:
            return jsonify({"error": "not found"}), 404

        produkt = ebr["produkt"]
        pipeline = pm.get_produkt_pipeline(db, produkt)

        # All sessions for this EBR
        all_sesje = pm.list_sesje(db, ebr_id)

        # Group by etap_id
        sesje_by_etap: dict[int, list] = {}
        for s in all_sesje:
            sesje_by_etap.setdefault(s["etap_id"], []).append(s)

        enriched = []
        for step in pipeline:
            etap_id = step["etap_id"]
            sesje = sesje_by_etap.get(etap_id, [])
            last = sesje[-1] if sesje else None
            enriched.append({
                **step,
                "sesja_count": len(sesje),
                "last_status": last["status"] if last else None,
                "last_runda": last["runda"] if last else None,
            })

        return jsonify(enriched)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /api/pipeline/lab/ebr/<ebr_id>/etap/<etap_id>
# Everything needed to render a stage form.
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/etap/<int:etap_id>", methods=["GET"])
@login_required
def lab_get_etap_form(ebr_id, etap_id):
    db = get_db()
    try:
        ebr = db.execute(
            """SELECT e.ebr_id, m.produkt
               FROM ebr_batches e
               JOIN mbr_templates m ON m.mbr_id = e.mbr_id
               WHERE e.ebr_id = ?""",
            (ebr_id,),
        ).fetchone()
        if ebr is None:
            return jsonify({"error": "not found"}), 404

        produkt = ebr["produkt"]
        etap = pm.get_etap(db, etap_id)
        parametry = pm.resolve_limity(db, produkt, etap_id)
        warunki = pm.list_etap_warunki(db, etap_id)
        korekty_katalog = pm.list_etap_korekty(db, etap_id)
        sesje = pm.list_sesje(db, ebr_id, etap_id=etap_id)

        current_sesja = sesje[-1] if sesje else None
        pomiary = pm.get_pomiary(db, current_sesja["id"]) if current_sesja else []

        return jsonify({
            "etap": etap,
            "parametry": parametry,
            "warunki": warunki,
            "korekty_katalog": korekty_katalog,
            "sesje": sesje,
            "current_sesja": current_sesja,
            "pomiary": pomiary,
        })
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /api/pipeline/lab/ebr/<ebr_id>/etap/<etap_id>/start
# Create a new analysis session (new runda).
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/etap/<int:etap_id>/start", methods=["POST"])
@login_required
def lab_start_sesja(ebr_id, etap_id):
    db = get_db()
    try:
        existing = pm.list_sesje(db, ebr_id, etap_id=etap_id)
        runda = len(existing) + 1
        laborant = session["user"]["login"]
        sesja_id = pm.create_sesja(db, ebr_id, etap_id, runda=runda, laborant=laborant)
        db.commit()
        return jsonify({"sesja_id": sesja_id, "runda": runda}), 201
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /api/pipeline/lab/ebr/<ebr_id>/etap/<etap_id>/pomiary
# Save measurements + evaluate gate.
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/etap/<int:etap_id>/pomiary", methods=["POST"])
@login_required
def lab_save_pomiary(ebr_id, etap_id):
    data = request.get_json(force=True) or {}
    sesja_id = data.get("sesja_id")
    pomiary_input = data.get("pomiary", [])

    db = get_db()
    try:
        # Resolve produkt for limit lookup
        ebr = db.execute(
            """SELECT e.ebr_id, m.produkt
               FROM ebr_batches e
               JOIN mbr_templates m ON m.mbr_id = e.mbr_id
               WHERE e.ebr_id = ?""",
            (ebr_id,),
        ).fetchone()
        if ebr is None:
            return jsonify({"error": "not found"}), 404

        produkt = ebr["produkt"]
        resolved = pm.resolve_limity(db, produkt, etap_id)
        limits_by_pid = {r["parametr_id"]: r for r in resolved}

        wpisal = session["user"]["login"]
        for p in pomiary_input:
            pid = p["parametr_id"]
            wartosc = p.get("wartosc")
            is_manual = int(p.get("is_manual", 1))
            lim = limits_by_pid.get(pid, {})
            pm.save_pomiar(
                db,
                sesja_id=sesja_id,
                parametr_id=pid,
                wartosc=wartosc,
                min_limit=lim.get("min_limit"),
                max_limit=lim.get("max_limit"),
                wpisal=wpisal,
                is_manual=is_manual,
            )

        # Auto-transition session from 'nierozpoczety' to 'w_trakcie'
        db.execute(
            "UPDATE ebr_etap_sesja SET status='w_trakcie' WHERE id=? AND status='nierozpoczety'",
            (sesja_id,),
        )

        db.commit()

        gate = pm.evaluate_gate(db, etap_id, sesja_id)
        pomiary_out = pm.get_pomiary(db, sesja_id)

        return jsonify({"gate": gate, "pomiary": pomiary_out})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /api/pipeline/lab/ebr/<ebr_id>/etap/<etap_id>/close
# Close a session with decision.
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/etap/<int:etap_id>/close", methods=["POST"])
@login_required
def lab_close_sesja(ebr_id, etap_id):
    data = request.get_json(force=True) or {}
    sesja_id = data.get("sesja_id")
    decyzja = data.get("decyzja")

    db = get_db()
    try:
        if decyzja == "zamknij_etap":
            db.execute(
                "UPDATE ebr_etap_sesja SET status='zamkniety', decyzja='zamknij_etap', dt_end=datetime('now') WHERE id=?",
                (sesja_id,),
            )
        elif decyzja == "reopen_etap":
            db.execute(
                "UPDATE ebr_etap_sesja SET status='w_trakcie', decyzja='reopen_etap', dt_end=NULL WHERE id=?",
                (sesja_id,),
            )
        else:
            pm.close_sesja(db, sesja_id, decyzja, komentarz=data.get("komentarz"))
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /api/pipeline/lab/ebr/<ebr_id>/korekta
# Create a correction recommendation.
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/korekta", methods=["POST"])
@login_required
def lab_create_korekta(ebr_id):
    data = request.get_json(force=True) or {}
    sesja_id = data.get("sesja_id")
    korekta_typ_id = data.get("korekta_typ_id")
    ilosc = data.get("ilosc")
    zalecil = session["user"]["login"]

    db = get_db()
    try:
        kid = pm.create_ebr_korekta(db, sesja_id, korekta_typ_id, ilosc, zalecil)
        db.commit()
        return jsonify({"id": kid}), 201
    finally:
        db.close()


# ---------------------------------------------------------------------------
# PUT /api/pipeline/lab/ebr/<ebr_id>/korekta/<korekta_id>/status
# Update correction status.
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/korekta/<int:korekta_id>/status", methods=["PUT"])
@login_required
def lab_update_korekta_status(ebr_id, korekta_id):
    data = request.get_json(force=True) or {}
    status = data.get("status")
    wykonawca_info = data.get("wykonawca_info")

    db = get_db()
    try:
        pm.update_ebr_korekta_status(db, korekta_id, status, wykonawca_info)
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /api/pipeline/lab/ebr/<ebr_id>/zlecenie-korekty
# Create a multi-substance correction order (zlecenie).
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/zlecenie-korekty", methods=["POST"])
@login_required
def lab_zlecenie_korekty(ebr_id):
    data = request.get_json(force=True) or {}
    sesja_id = data["sesja_id"]
    items = data["items"]
    komentarz = data.get("komentarz")
    zalecil = session.get("user", {}).get("login", "unknown")

    db = get_db()
    try:
        zlecenie_id = pm.create_zlecenie_korekty(
            db, sesja_id, items, zalecil=zalecil, komentarz=komentarz,
        )
        db.commit()
        zlecenie = pm.get_zlecenie(db, zlecenie_id)
        return jsonify({"ok": True, "zlecenie_id": zlecenie_id, "zlecenie": zlecenie})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /api/pipeline/lab/ebr/<ebr_id>/wykonaj-korekte
# Execute a correction order — marks it done and creates a new session.
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/wykonaj-korekte", methods=["POST"])
@login_required
def lab_wykonaj_korekte(ebr_id):
    data = request.get_json(force=True) or {}
    zlecenie_id = data["zlecenie_id"]

    db = get_db()
    try:
        new_sesja_id = pm.wykonaj_zlecenie(db, zlecenie_id)
        db.commit()
        return jsonify({"ok": True, "new_sesja_id": new_sesja_id})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /api/pipeline/lab/formula-hint
# Compute a formula hint for a correction type.
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/lab/formula-hint", methods=["GET"])
@login_required
def lab_formula_hint():
    korekta_typ_id = request.args.get("korekta_typ_id", type=int)
    zmienne = {k: float(v) for k, v in request.args.items() if k != "korekta_typ_id"}

    db = get_db()
    try:
        result = pm.compute_formula_hint(db, korekta_typ_id, zmienne)
        return jsonify({"ok": True, "hint": result})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /api/pipeline/lab/etap/<etap_id>/korekty-katalog
# Return available correction types for a stage.
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/lab/etap/<int:etap_id>/korekty-katalog", methods=["GET"])
@login_required
def lab_korekty_katalog(etap_id):
    db = get_db()
    try:
        rows = db.execute(
            """SELECT id, substancja, jednostka, wykonawca, kolejnosc,
                      formula_ilosc, formula_zmienne, formula_opis
               FROM etap_korekty_katalog
               WHERE etap_id = ?
               ORDER BY kolejnosc""",
            (etap_id,),
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        db.close()
