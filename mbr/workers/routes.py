from datetime import datetime

from flask import request, session, jsonify

from mbr.workers import workers_bp
from mbr.shared.decorators import login_required
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
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        worker_ids = [int(x) for x in data.get("worker_ids", []) if isinstance(x, (int, float))]
        session["shift_workers"] = worker_ids
        return jsonify({"ok": True})
    return jsonify({"worker_ids": session.get("shift_workers", [])})


@workers_bp.route("/api/worker/<int:worker_id>/profile", methods=["POST"])
@login_required
def api_worker_profile(worker_id):
    data = request.get_json(silent=True) or {}
    with db_session() as db:
        update_worker_profile(db, worker_id,
            nickname=data.get("nickname"),
            avatar_icon=data.get("avatar_icon"),
            avatar_color=data.get("avatar_color"))
    return jsonify({"ok": True})


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
