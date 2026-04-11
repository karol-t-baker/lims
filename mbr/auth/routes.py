from flask import redirect, url_for, request, session, render_template, jsonify

from mbr.auth import auth_bp
from mbr.shared.decorators import login_required, role_required
from mbr.db import db_session
from mbr.auth.models import verify_user, change_password
from mbr.shared import audit


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        login_val = request.form.get("login", "")
        password = request.form.get("password", "")
        with db_session() as db:
            user = verify_user(db, login_val, password)
            if user:
                session["user"] = {
                    "login": user["login"],
                    "rola": user["rola"],
                    "imie_nazwisko": user.get("imie_nazwisko"),
                }
                audit.log_event(
                    audit.EVENT_AUTH_LOGIN,
                    payload={"attempted_login": login_val},
                    actors=[{
                        "worker_id": None,
                        "actor_login": user["login"],
                        "actor_rola": user["rola"],
                    }],
                    db=db,
                )
                db.commit()
                return redirect(url_for("auth.index"))

            # Failure path: log with explicit unknown actor
            audit.log_event(
                audit.EVENT_AUTH_LOGIN,
                payload={"attempted_login": login_val},
                actors=[{
                    "worker_id": None,
                    "actor_login": login_val,
                    "actor_rola": "unknown",
                }],
                result="error",
                db=db,
            )
            db.commit()
        error = "Nieprawidłowy login lub hasło"
    return render_template("login.html", error=error)


@auth_bp.route("/logout")
def logout():
    if "user" in session:
        user = session["user"]
        with db_session() as db:
            audit.log_event(
                audit.EVENT_AUTH_LOGOUT,
                actors=[{
                    "worker_id": None,
                    "actor_login": user["login"],
                    "actor_rola": user["rola"],
                }],
                db=db,
            )
            db.commit()
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.route("/")
@login_required
def index():
    rola = session["user"]["rola"]
    if rola == "technolog":
        return redirect(url_for("technolog.mbr_list"))
    if rola == "admin":
        return redirect(url_for("admin.admin_panel"))
    return redirect(url_for("laborant.szarze_list"))


@auth_bp.route("/api/users/<int:user_id>/password", methods=["POST"])
@role_required("admin")
def api_change_password(user_id):
    """Admin changes another user's password.

    Body: {"new_password": "..."} (min 6 chars)
    Logs auth.password_changed with target user info — never the password itself.
    """
    body = request.get_json(silent=True) or {}
    new_password = body.get("new_password", "")
    if len(new_password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    with db_session() as db:
        try:
            user = change_password(db, user_id, new_password)
        except ValueError as e:
            msg = str(e)
            status = 404 if "not found" in msg else 400
            return jsonify({"error": msg}), status

        audit.log_event(
            audit.EVENT_AUTH_PASSWORD_CHANGED,
            entity_type="user",
            entity_id=user_id,
            entity_label=user["login"],
            payload={
                "target_user_id": user_id,
                "target_user_login": user["login"],
            },
            db=db,
        )
        db.commit()

    return jsonify({"ok": True})
