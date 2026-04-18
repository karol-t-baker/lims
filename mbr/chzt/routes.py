"""ChZT Flask handlers."""

from datetime import date

from flask import jsonify, session

from mbr.chzt import chzt_bp
from mbr.chzt.models import get_or_create_session, get_session_with_pomiary
from mbr.db import db_session
from mbr.shared.audit import log_event
from mbr.shared.decorators import login_required, role_required


ROLES_EDIT = ("lab", "kj", "cert", "technolog", "admin")


def _current_worker_id(db):
    """Resolve session user → workers.id.

    For 'lab'/'cert' roles, returns the FIRST shift worker id (sessions can have
    multiple, but a single id is sufficient as `updated_by`; audit retains the
    full shift via actors_from_request).
    For other roles, returns None (audit still records actor, but updated_by
    column will be NULL — that's fine; NULL is used for non-laborant writes).
    """
    user = session.get("user") or {}
    rola = user.get("rola")
    if rola in ("lab", "cert"):
        sw = session.get("shift_workers") or []
        return sw[0] if sw else None
    return None


@chzt_bp.route("/api/chzt/session/today", methods=["GET"])
@role_required(*ROLES_EDIT)
def api_session_today():
    today = date.today().isoformat()
    with db_session() as db:
        worker_id = _current_worker_id(db)
        session_id, created = get_or_create_session(db, today, created_by=worker_id, n_kontenery=8)
        if created:
            log_event(
                "chzt.session.created",
                entity_type="chzt_sesje",
                entity_id=session_id,
                entity_label=today,
                db=db,
            )
        db.commit()
        payload = get_session_with_pomiary(db, session_id)
    return jsonify({"session": payload})
