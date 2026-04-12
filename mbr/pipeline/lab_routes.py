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
