"""ChZT Flask handlers."""

from datetime import date

from flask import jsonify, request, session

from mbr.chzt import chzt_bp
from mbr.chzt.models import (
    get_or_create_session,
    get_session_with_pomiary,
    get_pomiar,
    update_pomiar,
    resize_kontenery,
    validate_for_finalize,
    finalize_session,
    unfinalize_session,
    list_sessions_paginated,
    POMIAR_FIELDS,
)
from mbr.db import db_session
from mbr.shared.audit import (
    log_event,
    diff_fields,
    EVENT_CHZT_SESSION_CREATED,
    EVENT_CHZT_SESSION_N_KONTENERY_CHANGED,
    EVENT_CHZT_POMIAR_UPDATED,
    EVENT_CHZT_SESSION_FINALIZED,
    EVENT_CHZT_SESSION_UNFINALIZED,
)
from mbr.shared.decorators import login_required, role_required


ROLES_EDIT = ("lab", "kj", "cert", "technolog", "admin")


def _coerce_float(v):
    """Coerce incoming JSON value to float; None/missing stays None; invalid → None.

    The JS client sends parsed floats, but robustness at the API boundary matters
    because autosave fires every 400ms and a single string breaking a PUT would
    both crash srednia math and pollute the audit log with phantom diffs.
    """
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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
                EVENT_CHZT_SESSION_CREATED,
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
    new_values = {k: _coerce_float(payload.get(k)) for k in POMIAR_FIELDS}

    with db_session() as db:
        old = get_pomiar(db, pomiar_id)
        if old is None:
            return jsonify({"error": "pomiar nie istnieje"}), 404

        changes = diff_fields(old, new_values, list(POMIAR_FIELDS))
        updated = update_pomiar(db, pomiar_id, new_values, updated_by=_current_worker_id())

        if changes:
            log_event(
                EVENT_CHZT_POMIAR_UPDATED,
                entity_type="chzt_pomiary",
                entity_id=pomiar_id,
                entity_label=old["punkt_nazwa"],
                diff=changes,
                context={"sesja_id": old["sesja_id"]},
                db=db,
            )
        db.commit()

    return jsonify({"pomiar": updated})


@chzt_bp.route("/api/chzt/session/<int:session_id>", methods=["PATCH"])
@role_required(*ROLES_EDIT)
def api_session_patch(session_id: int):
    payload = request.get_json(force=True) or {}
    new_n = payload.get("n_kontenery")
    if not isinstance(new_n, int) or new_n < 0 or new_n > 50:
        return jsonify({"error": "n_kontenery: oczekuję int 0..50"}), 400

    with db_session() as db:
        srow = db.execute("SELECT n_kontenery FROM chzt_sesje WHERE id=?", (session_id,)).fetchone()
        if srow is None:
            return jsonify({"error": "sesja nie istnieje"}), 404
        old_n = srow["n_kontenery"]
        try:
            resize_kontenery(db, session_id, new_n=new_n)
        except ValueError as e:
            return jsonify({"error": str(e)}), 409

        if new_n != old_n:
            log_event(
                EVENT_CHZT_SESSION_N_KONTENERY_CHANGED,
                entity_type="chzt_sesje",
                entity_id=session_id,
                diff=[{"pole": "n_kontenery", "stara": old_n, "nowa": new_n}],
                db=db,
            )
        db.commit()
        payload_out = get_session_with_pomiary(db, session_id)
    return jsonify({"session": payload_out})


@chzt_bp.route("/api/chzt/session/<int:session_id>/finalize", methods=["POST"])
@role_required(*ROLES_EDIT)
def api_session_finalize(session_id: int):
    with db_session() as db:
        if db.execute("SELECT 1 FROM chzt_sesje WHERE id=?", (session_id,)).fetchone() is None:
            return jsonify({"error": "sesja nie istnieje"}), 404
        errors = validate_for_finalize(db, session_id)
        if errors:
            return jsonify({"error": "walidacja", "errors": errors}), 400
        finalize_session(db, session_id, finalized_by=_current_worker_id())
        log_event(
            EVENT_CHZT_SESSION_FINALIZED,
            entity_type="chzt_sesje",
            entity_id=session_id,
            db=db,
        )
        db.commit()
        payload = get_session_with_pomiary(db, session_id)
    return jsonify({"session": payload})


@chzt_bp.route("/api/chzt/session/<int:session_id>/unfinalize", methods=["POST"])
@role_required("admin")
def api_session_unfinalize(session_id: int):
    with db_session() as db:
        if db.execute("SELECT 1 FROM chzt_sesje WHERE id=?", (session_id,)).fetchone() is None:
            return jsonify({"error": "sesja nie istnieje"}), 404
        unfinalize_session(db, session_id)
        log_event(
            EVENT_CHZT_SESSION_UNFINALIZED,
            entity_type="chzt_sesje",
            entity_id=session_id,
            db=db,
        )
        db.commit()
        payload = get_session_with_pomiary(db, session_id)
    return jsonify({"session": payload})


@chzt_bp.route("/api/chzt/session/<data_iso>", methods=["GET"])
@role_required(*ROLES_EDIT)
def api_session_by_date(data_iso: str):
    with db_session() as db:
        row = db.execute("SELECT id FROM chzt_sesje WHERE data=?", (data_iso,)).fetchone()
        if row is None:
            return jsonify({"error": "brak sesji dla tej daty"}), 404
        payload = get_session_with_pomiary(db, row["id"])
    return jsonify({"session": payload})


@chzt_bp.route("/api/chzt/day/<data_iso>", methods=["GET"])
@role_required(*ROLES_EDIT)
def api_day_frame(data_iso: str):
    """Export frame for Excel-filling script. Finalized sessions only."""
    with db_session() as db:
        row = db.execute(
            "SELECT id, data, finalized_at FROM chzt_sesje WHERE data=? AND finalized_at IS NOT NULL",
            (data_iso,),
        ).fetchone()
        if row is None:
            return jsonify({"error": "brak sfinalizowanej sesji"}), 404
        prows = db.execute(
            "SELECT punkt_nazwa, ph, srednia FROM chzt_pomiary "
            "WHERE sesja_id=? ORDER BY kolejnosc",
            (row["id"],),
        ).fetchall()
        punkty = [
            {"nazwa": p["punkt_nazwa"], "ph": p["ph"], "srednia": p["srednia"]}
            for p in prows
        ]
    return jsonify({
        "data": row["data"],
        "finalized_at": row["finalized_at"],
        "punkty": punkty,
    })


@chzt_bp.route("/api/chzt/history", methods=["GET"])
@role_required(*ROLES_EDIT)
def api_history():
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    with db_session() as db:
        payload = list_sessions_paginated(db, page=page, per_page=10)
    return jsonify(payload)


@chzt_bp.route("/api/chzt/session/<int:session_id>/audit-history", methods=["GET"])
@role_required(*ROLES_EDIT)
def api_session_audit_history(session_id: int):
    """Return all audit entries for this session and its pomiary rows, newest-first."""
    with db_session() as db:
        pomiar_ids = [
            r["id"] for r in db.execute(
                "SELECT id FROM chzt_pomiary WHERE sesja_id=?", (session_id,)
            ).fetchall()
        ]
        rows_session = db.execute(
            "SELECT id, dt, event_type, entity_type, entity_id, entity_label, "
            "       diff_json FROM audit_log "
            "WHERE entity_type='chzt_sesje' AND entity_id=?",
            (session_id,),
        ).fetchall()
        rows_pomiar = []
        if pomiar_ids:
            placeholders = ",".join("?" * len(pomiar_ids))
            rows_pomiar = db.execute(
                f"SELECT id, dt, event_type, entity_type, entity_id, entity_label, "
                f"       diff_json FROM audit_log "
                f"WHERE entity_type='chzt_pomiary' AND entity_id IN ({placeholders})",
                pomiar_ids,
            ).fetchall()
        all_rows = sorted(
            [dict(r) for r in list(rows_session) + list(rows_pomiar)],
            key=lambda r: r["dt"],
            reverse=True,
        )
    return jsonify({"entries": all_rows})
