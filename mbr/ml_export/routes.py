"""CSV export endpoint for ML-ready K7 batch data."""
import csv
import io

from flask import request, Response

from mbr.ml_export import ml_export_bp
from mbr.ml_export.query import export_k7_batches, CSV_COLUMNS
from mbr.db import get_db
from mbr.shared.decorators import role_required


@ml_export_bp.route("/api/export/ml/k7.csv", methods=["GET"])
@role_required("admin")
def export_k7_csv():
    after_id = request.args.get("after_id", 0, type=int)
    db = get_db()
    try:
        rows = export_k7_batches(db, after_id=after_id)
    finally:
        db.close()

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    last_id = max((r["ebr_id"] for r in rows), default=after_id)
    resp = Response(output.getvalue(), mimetype="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = "attachment; filename=k7_ml_export.csv"
    resp.headers["X-Last-Id"] = str(last_id)
    return resp
