"""ChZT Flask handlers."""

from flask import jsonify, request, session, render_template

from mbr.chzt import chzt_bp
from mbr.chzt.models import (
    get_active_session, create_session, get_session_with_pomiary,
    get_pomiar, update_pomiar, resize_kontenery,
    validate_for_finalize, finalize_session, unfinalize_session,
    list_sessions_paginated,
    POMIAR_FIELDS, POMIAR_FIELDS_INTERNAL, POMIAR_FIELDS_EXTERNAL,
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


ROLES_VIEW = ("lab", "kj", "cert", "technolog", "admin", "produkcja")
ROLES_EDIT_INTERNAL = ("lab", "kj", "cert", "technolog", "admin")
ROLES_EDIT_EXTERNAL = ("produkcja", "technolog", "admin")


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


@chzt_bp.route("/api/chzt/session/active", methods=["GET"])
@role_required(*ROLES_VIEW)
def api_session_active():
    with db_session() as db:
        active = get_active_session(db)
        if active is None:
            return jsonify({"session": None})
        payload = get_session_with_pomiary(db, active["id"])
    return jsonify({"session": payload})


@chzt_bp.route("/api/chzt/session/new", methods=["POST"])
@role_required(*ROLES_EDIT_INTERNAL)
def api_session_create():
    payload = request.get_json(force=True) or {}
    n_kontenery = payload.get("n_kontenery", 8)
    if not isinstance(n_kontenery, int) or isinstance(n_kontenery, bool) or n_kontenery < 0 or n_kontenery > 20:
        return jsonify({"error": "n_kontenery: oczekuję int 0..20"}), 400

    with db_session() as db:
        try:
            session_id = create_session(
                db, created_by=_current_worker_id(), n_kontenery=n_kontenery
            )
        except ValueError as e:
            if "already_open" in str(e):
                return jsonify({"error": "Istnieje otwarta sesja — zakończ ją najpierw."}), 409
            raise
        log_event(
            EVENT_CHZT_SESSION_CREATED,
            entity_type="chzt_sesje",
            entity_id=session_id,
            db=db,
        )
        db.commit()
        payload_out = get_session_with_pomiary(db, session_id)
    return jsonify({"session": payload_out})


def _allowed_fields_for_role(rola: str) -> tuple:
    """Return the tuple of pomiar field names the given role may write."""
    if rola in ("admin", "technolog"):
        return POMIAR_FIELDS
    if rola in ("lab", "kj", "cert"):
        return POMIAR_FIELDS_INTERNAL
    if rola == "produkcja":
        return POMIAR_FIELDS_EXTERNAL
    return ()


@chzt_bp.route("/api/chzt/pomiar/<int:pomiar_id>", methods=["PUT"])
@role_required(*ROLES_VIEW)
def api_pomiar_update(pomiar_id: int):
    payload = request.get_json(force=True) or {}
    rola = session.get("user", {}).get("rola") or ""
    allowed = _allowed_fields_for_role(rola)

    # Filter: keep only allowed keys that are actually present in payload
    new_values = {}
    for k in allowed:
        if k in payload:
            new_values[k] = _coerce_float(payload[k])

    with db_session() as db:
        old = get_pomiar(db, pomiar_id)
        if old is None:
            return jsonify({"error": "pomiar nie istnieje"}), 404

        if not new_values:
            # Nothing writable — return current state without audit
            return jsonify({"pomiar": old})

        changes = diff_fields(old, new_values, list(new_values.keys()))

        try:
            updated = update_pomiar(db, pomiar_id, new_values, updated_by=_current_worker_id())
        except ValueError:
            return jsonify({"error": "pomiar nie istnieje"}), 404

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
@role_required(*ROLES_EDIT_INTERNAL)
def api_session_patch(session_id: int):
    payload = request.get_json(force=True) or {}
    new_n = payload.get("n_kontenery")
    if not isinstance(new_n, int) or isinstance(new_n, bool) or new_n < 0 or new_n > 20:
        return jsonify({"error": "n_kontenery: oczekuję int 0..20"}), 400

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
@role_required(*ROLES_EDIT_INTERNAL)
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


@chzt_bp.route("/api/chzt/session/<int:session_id>", methods=["GET"])
@role_required(*ROLES_VIEW)
def api_session_by_id(session_id: int):
    with db_session() as db:
        payload = get_session_with_pomiary(db, session_id)
        if payload is None:
            return jsonify({"error": "sesja nie istnieje"}), 404
    return jsonify({"session": payload})


@chzt_bp.route("/api/chzt/day/<data_iso>", methods=["GET"])
@role_required(*ROLES_VIEW)
def api_day_frame(data_iso: str):
    """Export frame for Excel script. Returns newest finalized session whose
    DATE(dt_start) matches. Max 1/day guaranteed by policy — LIMIT 1.
    Includes ext fields (ext_chzt, ext_ph, waga_kg)."""
    with db_session() as db:
        row = db.execute(
            "SELECT id, dt_start, finalized_at "
            "FROM chzt_sesje "
            "WHERE DATE(dt_start) = ? AND finalized_at IS NOT NULL "
            "ORDER BY dt_start DESC LIMIT 1",
            (data_iso,),
        ).fetchone()
        if row is None:
            return jsonify({"error": "brak sfinalizowanej sesji"}), 404
        prows = db.execute(
            "SELECT punkt_nazwa, ph, srednia, ext_chzt, ext_ph, waga_kg "
            "FROM chzt_pomiary WHERE sesja_id=? ORDER BY kolejnosc",
            (row["id"],),
        ).fetchall()
        punkty = [
            {
                "nazwa": p["punkt_nazwa"],
                "ph": p["ph"],
                "srednia": p["srednia"],
                "ext_chzt": p["ext_chzt"],
                "ext_ph": p["ext_ph"],
                "waga_kg": p["waga_kg"],
            }
            for p in prows
        ]
    return jsonify({
        "dt_start": row["dt_start"],
        "finalized_at": row["finalized_at"],
        "punkty": punkty,
    })


@chzt_bp.route("/api/chzt/history", methods=["GET"])
@role_required(*ROLES_VIEW)
def api_history():
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    with db_session() as db:
        payload = list_sessions_paginated(db, page=page, per_page=10)
    return jsonify(payload)


@chzt_bp.route("/chzt/historia", methods=["GET"])
@role_required(*ROLES_VIEW)
def historia_page():
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    with db_session() as db:
        data = list_sessions_paginated(db, page=page, per_page=10)
    return render_template(
        "chzt_historia.html",
        sesje=data["sesje"],
        total=data["total"],
        page=data["page"],
        pages=data["pages"],
    )


