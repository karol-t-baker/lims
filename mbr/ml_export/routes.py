"""HTTP endpoints + admin page for the ML export package."""
from datetime import date

from flask import abort, jsonify, request, Response, render_template

from mbr.db import get_db
from mbr.ml_export import ml_export_bp
from mbr.ml_export.edit import get_batch_detail, update_batch, update_session, update_measurement, update_correction
from mbr.ml_export.query import export_ml_package, build_batches, build_sessions, \
    build_measurements, build_corrections
from mbr.shared.decorators import role_required


def _statuses(include_failed: bool) -> tuple[str, ...]:
    return ("completed", "cancelled") if include_failed else ("completed",)


def _include_failed_param() -> bool:
    return request.args.get("include_failed", "0") in ("1", "true", "yes")


@ml_export_bp.route("/api/export/ml/k7.csv", methods=["GET"])
def export_k7_csv_gone():
    abort(404)


@ml_export_bp.route("/api/export/ml/k7.zip", methods=["GET"])
@role_required("admin")
def export_k7_zip():
    db = get_db()
    try:
        blob = export_ml_package(db, produkty=["Chegina_K7"], statuses=_statuses(_include_failed_param()))
    finally:
        db.close()
    fname = f"k7_ml_export_{date.today().isoformat()}.zip"
    resp = Response(blob, mimetype="application/zip")
    resp.headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp


@ml_export_bp.route("/ml-export", methods=["GET"])
@role_required("admin")
def ml_export_page():
    include_failed = _include_failed_param()
    db = get_db()
    try:
        batches      = build_batches(db, produkty=["Chegina_K7"], statuses=_statuses(include_failed))
        ebr_ids      = [b["ebr_id"] for b in batches]
        sessions     = build_sessions(db, ebr_ids)
        measurements = build_measurements(db, ebr_ids)
        corrections  = build_corrections(db, ebr_ids)
    finally:
        db.close()

    preview = {
        "batches":      {"total": len(batches),      "rows": batches[:5]},
        "sessions":     {"total": len(sessions),     "rows": sessions[:5]},
        "measurements": {"total": len(measurements), "rows": measurements[:5]},
        "corrections":  {"total": len(corrections),  "rows": corrections[:5]},
    }
    return render_template("ml_export/ml_export.html",
                           preview=preview, include_failed=include_failed)


@ml_export_bp.route("/api/ml-export/batch-detail", methods=["GET"])
@role_required("admin")
def ml_batch_detail():
    nr_partii = request.args.get("nr_partii")
    if not nr_partii:
        abort(400, description="nr_partii is required")
    db = get_db()
    try:
        detail = get_batch_detail(db, nr_partii)
    finally:
        db.close()
    if detail is None:
        abort(404)
    return jsonify(detail)


@ml_export_bp.route("/api/ml-export/batch/<int:ebr_id>", methods=["PUT"])
@role_required("admin")
def ml_put_batch(ebr_id: int):
    fields = request.get_json(force=True) or {}
    db = get_db()
    try:
        ok, err = update_batch(db, ebr_id, fields)
    finally:
        db.close()
    if not ok:
        if err == "NOT_FOUND":
            abort(404)
        abort(400, description=err)
    return jsonify({"ok": True, "new_value": list(fields.values())[0] if len(fields) == 1 else fields})


@ml_export_bp.route("/api/ml-export/session/<int:sesja_id>", methods=["PUT"])
@role_required("admin")
def ml_put_session(sesja_id: int):
    fields = request.get_json(force=True) or {}
    db = get_db()
    try:
        ok, err = update_session(db, sesja_id, fields)
    finally:
        db.close()
    if not ok:
        if err == "NOT_FOUND":
            abort(404)
        abort(400, description=err)
    return jsonify({"ok": True, "new_value": list(fields.values())[0] if len(fields) == 1 else fields})


@ml_export_bp.route("/api/ml-export/measurement/<source>/<int:row_id>", methods=["PUT"])
@role_required("admin")
def ml_put_measurement(source: str, row_id: int):
    fields = request.get_json(force=True) or {}
    db = get_db()
    try:
        ok, err = update_measurement(db, source, row_id, fields)
    finally:
        db.close()
    if not ok:
        if err == "NOT_FOUND":
            abort(404)
        abort(400, description=err)
    return jsonify({"ok": True, "new_value": list(fields.values())[0] if len(fields) == 1 else fields})


@ml_export_bp.route("/api/ml-export/correction/<int:korekta_id>", methods=["PUT"])
@role_required("admin")
def ml_put_correction(korekta_id: int):
    fields = request.get_json(force=True) or {}
    db = get_db()
    try:
        ok, err = update_correction(db, korekta_id, fields)
    finally:
        db.close()
    if not ok:
        if err == "NOT_FOUND":
            abort(404)
        abort(400, description=err)
    return jsonify({"ok": True, "new_value": list(fields.values())[0] if len(fields) == 1 else fields})
