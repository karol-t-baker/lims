"""ChZT Flask handlers."""

from datetime import date

from flask import jsonify, request, session

from mbr.chzt import chzt_bp
from mbr.chzt.models import (
    get_or_create_session,
    get_session_with_pomiary,
    get_pomiar,
    update_pomiar,
    POMIAR_FIELDS,
)
from mbr.db import db_session
from mbr.shared.audit import diff_fields, log_event
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


@chzt_bp.route("/api/chzt/pomiar/<int:pomiar_id>", methods=["PUT"])
@role_required(*ROLES_EDIT)
def api_pomiar_update(pomiar_id: int):
    payload = request.get_json(force=True) or {}
    new_values = {k: payload.get(k) for k in POMIAR_FIELDS}

    with db_session() as db:
        old = get_pomiar(db, pomiar_id)
        if old is None:
            return jsonify({"error": "pomiar nie istnieje"}), 404

        changes = diff_fields(old, new_values, list(POMIAR_FIELDS))
        updated = update_pomiar(db, pomiar_id, new_values, updated_by=_current_worker_id())

        if changes:
            log_event(
                "chzt.pomiar.updated",
                entity_type="chzt_pomiary",
                entity_id=pomiar_id,
                entity_label=old["punkt_nazwa"],
                diff=changes,
                context={"sesja_id": old["sesja_id"]},
                db=db,
            )
        db.commit()

    return jsonify({"pomiar": updated})
