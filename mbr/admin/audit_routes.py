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
    page_size = 100
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
