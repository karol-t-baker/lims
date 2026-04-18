"""ChZT Flask handlers."""

from datetime import date

from flask import jsonify, session

from mbr.chzt import chzt_bp
from mbr.chzt.models import get_or_create_session, get_session_with_pomiary
from mbr.db import db_session
from mbr.shared.audit import log_event
from mbr.shared.decorators import login_required, role_required


ROLES_EDIT = ("lab", "kj", "cert", "technolog", "admin")


def _current_worker_id():
    """Resolve current session user → workers.id for the `updated_by`/`created_by`
    column. Returns the first shift worker id for roles `lab`/`cert`. Other roles
    (`kj`, `technolog`, `admin`) have no shift_workers and return None — that is
    fine, `updated_by` is nullable. Audit-level actor resolution still happens
    via `actors_from_request(db)` in `log_event`, so identity is not lost.
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
        worker_id = _current_worker_id()
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
