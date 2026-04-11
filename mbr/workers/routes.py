from datetime import datetime

from flask import request, session, jsonify

from mbr.workers import workers_bp
from mbr.shared.decorators import login_required
from mbr.shared import audit
from mbr.db import db_session
from mbr.workers.models import list_workers, update_worker_profile


@workers_bp.route("/api/workers")
@login_required
def api_workers():
    with db_session() as db:
        workers = list_workers(db)
    return jsonify({"workers": workers})


@workers_bp.route("/api/shift", methods=["GET", "POST"])
@login_required
def api_shift():
    """Shift workers — shared globally via DB (same shift across all devices)."""
    import json as _json
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        worker_ids = [int(x) for x in data.get("worker_ids", []) if isinstance(x, (int, float))]
        with db_session() as db:
            # Read old value for the audit diff
            old_row = db.execute(
                "SELECT value FROM user_settings WHERE login='_system_' AND key='current_shift'"
            ).fetchone()
            old_ids = _json.loads(old_row["value"]) if old_row and old_row["value"] else []

            session["shift_workers"] = worker_ids
            db.execute(
                """INSERT INTO user_settings (login, key, value) VALUES ('_system_', 'current_shift', ?)
                   ON CONFLICT(login, key) DO UPDATE SET value=excluded.value""",
                (_json.dumps(worker_ids),),
            )
            # Explicit actor — never use actors_from_request here, because
            # session['shift_workers'] is what's being SET right now and would
            # crash actors_from_request for rola='laborant' even if shift is
            # empty before this call.
            user = session.get("user", {})
            audit.log_event(
                audit.EVENT_SHIFT_CHANGED,
                entity_type="shift",
                payload={"old": old_ids, "new": worker_ids},
                actors=[{
                    "worker_id": None,
                    "actor_login": user.get("login", "unknown"),
                    "actor_rola": user.get("rola", "unknown"),
                }],
                db=db,
            )
            db.commit()
        return jsonify({"ok": True})
    # GET: read from DB (shared), sync to session
    with db_session() as db:
        row = db.execute(
            "SELECT value FROM user_settings WHERE login='_system_' AND key='current_shift'"
        ).fetchone()
    if row and row["value"]:
        worker_ids = _json.loads(row["value"])
        session["shift_workers"] = worker_ids
        return jsonify({"worker_ids": worker_ids})
    return jsonify({"worker_ids": session.get("shift_workers", [])})


@workers_bp.route("/api/worker/<int:worker_id>/profile", methods=["POST"])
@login_required
def api_worker_profile(worker_id):
    data = request.get_json(silent=True) or {}
    with db_session() as db:
        # Snapshot before for the diff
        old_row = db.execute(
            "SELECT imie, nazwisko, nickname, avatar_icon, avatar_color FROM workers WHERE id=?",
            (worker_id,),
        ).fetchone()
        if old_row is None:
            return jsonify({"error": "not found"}), 404
        old = dict(old_row)

        # Build the UPDATE inline so it stays in our transaction. The model
        # helper update_worker_profile commits internally, which would split
        # the UPDATE and audit log INSERT across two separate commits.
        sets = []
        vals = []
        if data.get("nickname") is not None:
            sets.append("nickname = ?")
            vals.append(data["nickname"])
        if data.get("avatar_icon") is not None:
            sets.append("avatar_icon = ?")
            vals.append(data["avatar_icon"])
        if data.get("avatar_color") is not None:
            sets.append("avatar_color = ?")
            vals.append(data["avatar_color"])
        if sets:
            vals.append(worker_id)
            db.execute(f"UPDATE workers SET {', '.join(sets)} WHERE id = ?", vals)

        new_row = db.execute(
            "SELECT nickname, avatar_icon, avatar_color FROM workers WHERE id=?",
            (worker_id,),
        ).fetchone()
        new = dict(new_row)

        diff = audit.diff_fields(old, new, ["nickname", "avatar_icon", "avatar_color"])
        if diff:
            user = session.get("user", {})
            audit.log_event(
                audit.EVENT_WORKER_UPDATED,
                entity_type="worker",
                entity_id=worker_id,
                entity_label=f"{old['imie']} {old['nazwisko']}",
                diff=diff,
                actors=[{
                    "worker_id": None,
                    "actor_login": user.get("login", "unknown"),
                    "actor_rola": user.get("rola", "unknown"),
                }],
                db=db,
            )
        db.commit()  # single commit covers both UPDATE and audit INSERT
    return jsonify({"ok": True})


@workers_bp.route("/api/workers", methods=["POST"])
@login_required
def api_add_worker():
    from mbr.workers.models import add_worker
    data = request.get_json(silent=True) or {}
    imie = (data.get("imie") or "").strip()
    nazwisko = (data.get("nazwisko") or "").strip()
    if not imie or not nazwisko:
        return jsonify({"error": "imie and nazwisko required"}), 400
    inicjaly = (imie[0] + nazwisko[0]).upper()
    nickname = (data.get("nickname") or "").strip()
    with db_session() as db:
        wid = add_worker(db, imie, nazwisko, inicjaly, nickname)
    return jsonify({"ok": True, "id": wid})


@workers_bp.route("/api/workers/<int:worker_id>/toggle", methods=["POST"])
@login_required
def api_toggle_worker(worker_id):
    from mbr.workers.models import toggle_worker_active
    with db_session() as db:
        new_val = toggle_worker_active(db, worker_id)
    if new_val is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True, "aktywny": new_val})


@workers_bp.route("/api/workers/<int:worker_id>", methods=["DELETE"])
@login_required
def api_delete_worker(worker_id):
    from mbr.workers.models import delete_worker
    with db_session() as db:
        delete_worker(db, worker_id)
    return jsonify({"ok": True})


@workers_bp.route("/api/workers/all")
@login_required
def api_workers_all():
    """All workers including inactive — for settings page."""
    with db_session() as db:
        workers = list_workers(db, aktywny=False)
    return jsonify({"workers": workers})


@workers_bp.route("/api/feedback", methods=["POST"])
@login_required
def api_feedback():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    who = (data.get("who") or "").strip()
    if not text:
        return jsonify({"error": "empty"}), 400
    now = datetime.now().isoformat(timespec="seconds")
    with db_session() as db:
        db.execute("INSERT INTO feedback (text, who, dt) VALUES (?, ?, ?)", (text, who, now))
        db.commit()
    return jsonify({"ok": True})
