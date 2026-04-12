"""Admin panel for the audit trail.

Routes:
  GET  /admin/audit                  — render the panel with filters/table
  GET  /admin/audit/export.csv       — stream CSV using same WHERE
  POST /admin/audit/archive/preview  — return count of rows that would be archived
  POST /admin/audit/archive          — actually run archival

All routes require role='admin'. See:
docs/superpowers/specs/2026-04-11-audit-trail-phase2-design.md
"""

import csv
import io
import json as _json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from flask import (
    Response,
    current_app,
    jsonify,
    render_template,
    request,
    stream_with_context,
)

from mbr.admin import admin_bp
from mbr.db import db_session
from mbr.shared import audit
from mbr.shared.decorators import role_required


def _csv_val(v):
    """CSV cell value: empty string for None, str(v) otherwise.
    Avoids the 'or' shortcut which silently drops legitimate 0 / False / ''."""
    return "" if v is None else v


# ---------- Filter parser + dropdown groups ----------

_EVENT_TYPE_GROUPS = [
    {"value": "", "label": "(wszystkie)"},
    {"value": "auth.*", "label": "auth.*"},
    {"value": "worker.*", "label": "worker.*"},
    {"value": "shift.*", "label": "shift.*"},
    {"value": "mbr.*", "label": "mbr.*"},
    {"value": "ebr.*", "label": "ebr.*"},
    {"value": "cert.*", "label": "cert.*"},
    {"value": "paliwo.*", "label": "paliwo.*"},
    {"value": "admin.*", "label": "admin.*"},
    {"value": "system.*", "label": "system.*"},
]

_ENTITY_TYPES = [
    {"value": "", "label": "(wszystkie)"},
    {"value": "ebr", "label": "EBR"},
    {"value": "mbr", "label": "MBR"},
    {"value": "cert", "label": "Świadectwo"},
    {"value": "worker", "label": "Pracownik"},
]


def _parse_filters_from_query(args) -> dict:
    """Translate request.args into kwargs for query_audit_log."""
    def _opt_str(key):
        v = args.get(key, "").strip()
        return v or None

    def _opt_int(key):
        v = args.get(key, "").strip()
        try:
            return int(v) if v else None
        except ValueError:
            return None

    return {
        "dt_from": _opt_str("dt_from"),
        "dt_to": _opt_str("dt_to"),
        "event_type_glob": _opt_str("event_type_glob"),
        "entity_type": _opt_str("entity_type"),
        "entity_id": _opt_int("entity_id"),
        "worker_id": _opt_int("worker_id"),
        "free_text": _opt_str("free_text"),
        "request_id": _opt_str("request_id"),
    }


# ---------- Routes ----------

@admin_bp.route("/admin/audit")
@role_required("admin")
def audit_panel():
    """Render the audit log panel with filters and a paginated table."""
    filters = _parse_filters_from_query(request.args)
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    page_size = 50
    offset = (page - 1) * page_size

    with db_session() as db:
        rows, total = audit.query_audit_log(
            db, **filters, limit=page_size, offset=offset
        )
        workers = db.execute(
            "SELECT id, nickname, inicjaly FROM workers WHERE aktywny=1 ORDER BY inicjaly"
        ).fetchall()

    # Parse JSON columns inside rows for template rendering
    for r in rows:
        if r.get("diff_json"):
            try:
                r["diff_parsed"] = _json.loads(r["diff_json"])
            except Exception:
                r["diff_parsed"] = None
        else:
            r["diff_parsed"] = None

    page_count = max(1, (total + page_size - 1) // page_size)

    # Build pager URL base — current query string minus 'page'
    qs_no_page = {k: v for k, v in request.args.items() if k != "page"}
    pager_base = "/admin/audit?" + urlencode(qs_no_page)
    if qs_no_page:
        pager_base += "&page="
    else:
        pager_base += "page="

    return render_template(
        "admin/audit.html",
        rows=rows,
        total=total,
        page=page,
        page_count=page_count,
        filters=request.args,
        workers=workers,
        event_groups=_EVENT_TYPE_GROUPS,
        entity_types=_ENTITY_TYPES,
        pager_base=pager_base,
    )


@admin_bp.route("/admin/audit/export.csv")
@role_required("admin")
def audit_export_csv():
    """Stream the audit log as CSV using the same WHERE as the panel.

    Note on memory: query_audit_log() materializes all matching rows via
    fetchall() before this generator yields. The streaming Response only
    benefits HTTP chunked transfer, not peak Python memory. The hard cap
    of 1,000,000 rows below is the actual memory safety valve. If real
    audit logs grow large enough that 1M rows in memory becomes a problem,
    refactor query_audit_log into a cursor-based iterator with per-batch
    actor bulk-loading. Tracking: Phase 7 cleanup. For now, the cap +
    typical row size of ~1KB bounds peak memory at ~1GB worst case, which
    is acceptable for an admin-triggered export.
    """
    filters = _parse_filters_from_query(request.args)

    def generate():
        # Header row
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow([
            "dt", "event_type", "entity_type", "entity_id", "entity_label",
            "actors", "result", "diff", "payload", "ip", "request_id",
        ])
        yield out.getvalue()

        with db_session() as db:
            rows, _total = audit.query_audit_log(
                db, **filters, limit=1_000_000, offset=0
            )
        for r in rows:
            out = io.StringIO()
            writer = csv.writer(out)
            actors_str = ", ".join(a["actor_login"] for a in (r.get("actors") or []))
            writer.writerow([
                _csv_val(r.get("dt")),
                _csv_val(r.get("event_type")),
                _csv_val(r.get("entity_type")),
                _csv_val(r.get("entity_id")),
                _csv_val(r.get("entity_label")),
                actors_str,
                _csv_val(r.get("result")),
                _csv_val(r.get("diff_json")),
                _csv_val(r.get("payload_json")),
                _csv_val(r.get("ip")),
                _csv_val(r.get("request_id")),
            ])
            yield out.getvalue()

    return Response(
        stream_with_context(generate()),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )


@admin_bp.route("/admin/audit/archive/preview", methods=["POST"])
@role_required("admin")
def audit_archive_preview():
    """Return count of audit_log rows that would be archived for the given cutoff.

    No mutation. Used by the modal confirmation dialog.
    """
    body = request.get_json(silent=True) or {}
    cutoff = body.get("cutoff_iso")
    if not cutoff:
        return jsonify({"error": "cutoff_iso required"}), 400
    with db_session() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM audit_log WHERE dt < ?", (cutoff,)
        ).fetchone()[0]
    return jsonify({"count": count, "cutoff": cutoff})


def _resolve_archive_dir() -> Path:
    """Default archive location: <project_root>/data/audit_archive/.

    Extracted into a helper so tests can monkey-patch it.
    """
    project_root = Path(current_app.root_path).parent
    return project_root / "data" / "audit_archive"


@admin_bp.route("/admin/audit/archive", methods=["POST"])
@role_required("admin")
def audit_archive_do():
    """Run the actual archival: dump old rows to JSONL.gz, delete from DB,
    log system.audit.archived. See audit.archive_old_entries() for details.
    """
    body = request.get_json(silent=True) or {}
    cutoff = body.get("cutoff_iso")
    if not cutoff:
        return jsonify({"error": "cutoff_iso required"}), 400

    archive_dir = _resolve_archive_dir()
    archive_dir.mkdir(parents=True, exist_ok=True)
    with db_session() as db:
        result = audit.archive_old_entries(db, cutoff, archive_dir)
    return jsonify(result)
