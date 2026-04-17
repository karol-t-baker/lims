"""CSV export endpoint + browser view for ML-ready K7 batch data."""
import csv
import io
import math

from flask import request, Response, render_template

from mbr.ml_export import ml_export_bp
from mbr.ml_export.query import export_k7_batches, get_csv_columns
from mbr.db import get_db
from mbr.shared.decorators import role_required

PER_PAGE = 25


@ml_export_bp.route("/api/export/ml/k7.csv", methods=["GET"])
@role_required("admin")
def export_k7_csv():
    after_id = request.args.get("after_id", 0, type=int)
    include_failed = request.args.get("include_failed", "0") in ("1", "true", "yes")
    statuses = ("completed", "cancelled") if include_failed else ("completed",)
    db = get_db()
    try:
        rows = export_k7_batches(db, after_id=after_id, statuses=statuses)
        columns = get_csv_columns(db)
    finally:
        db.close()

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    last_id = max((r["ebr_id"] for r in rows), default=after_id)
    resp = Response(output.getvalue(), mimetype="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = "attachment; filename=k7_ml_export.csv"
    resp.headers["X-Last-Id"] = str(last_id)
    return resp


@ml_export_bp.route("/ml-export", methods=["GET"])
@role_required("admin")
def ml_export_page():
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1
    include_failed = request.args.get("include_failed", "0") in ("1", "true", "yes")
    statuses = ("completed", "cancelled") if include_failed else ("completed",)
    db = get_db()
    try:
        all_rows = export_k7_batches(db, statuses=statuses)
        columns = get_csv_columns(db)
    finally:
        db.close()

    total = len(all_rows)
    total_pages = max(1, math.ceil(total / PER_PAGE))
    if page > total_pages:
        page = total_pages
    start = (page - 1) * PER_PAGE
    rows = all_rows[start:start + PER_PAGE]

    return render_template("ml_export/ml_export.html",
                           rows=rows, columns=columns,
                           page=page, total_pages=total_pages, total=total)
