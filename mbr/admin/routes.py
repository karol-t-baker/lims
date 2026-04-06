"""Admin panel — backup + feedback management."""

import os
import shutil
from datetime import datetime
from pathlib import Path

from flask import jsonify, render_template, request

from mbr.admin import admin_bp
from mbr.db import db_session, DB_PATH
from mbr.shared.decorators import role_required

PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "data" / "backups"
SWIADECTWA_DIR = PROJECT_ROOT / "data" / "swiadectwa"


def _get_backup_dir(db) -> Path:
    """Read backup_dir from system settings, fallback to default."""
    row = db.execute(
        "SELECT value FROM user_settings WHERE login='_system_' AND key='backup_dir'"
    ).fetchone()
    if row and row["value"]:
        p = Path(row["value"])
        return p if p.is_absolute() else PROJECT_ROOT / p
    return DEFAULT_BACKUP_DIR


def _set_backup_dir(db, path_str: str):
    """Save backup_dir to system settings."""
    db.execute(
        """INSERT INTO user_settings (login, key, value) VALUES ('_system_', 'backup_dir', ?)
           ON CONFLICT(login, key) DO UPDATE SET value=excluded.value""",
        (path_str,),
    )
    db.commit()


def _list_backups(backup_dir: Path) -> list[dict]:
    """List existing backup folders, newest first."""
    if not backup_dir.exists():
        return []
    backups = []
    for entry in sorted(backup_dir.iterdir(), reverse=True):
        if entry.is_dir() and entry.name.startswith("lims_backup_"):
            db_file = entry / "batch_db.sqlite"
            size_mb = db_file.stat().st_size / (1024 * 1024) if db_file.exists() else 0
            # Count JSON files
            json_count = sum(1 for _ in entry.rglob("*.json"))
            backups.append({
                "name": entry.name,
                "date": entry.name.replace("lims_backup_", "").replace("_", " ", 1).replace("-", ".", 2),
                "size_mb": round(size_mb, 1),
                "json_count": json_count,
                "path": str(entry),
            })
    return backups


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@admin_bp.route("/admin")
@role_required("admin")
def admin_panel():
    with db_session() as db:
        backup_dir = _get_backup_dir(db)
        feedback = db.execute(
            "SELECT * FROM feedback ORDER BY CASE priorytet WHEN 'pilne' THEN 0 ELSE 1 END, dt DESC"
        ).fetchall()
        feedback = [dict(r) for r in feedback]
    backups = _list_backups(backup_dir)
    return render_template(
        "admin/panel.html",
        backup_dir=str(backup_dir),
        backups=backups,
        feedback=feedback,
    )


@admin_bp.route("/api/admin/backup-dir", methods=["PUT"])
@role_required("admin")
def api_set_backup_dir():
    data = request.get_json(silent=True) or {}
    path_str = (data.get("path") or "").strip()
    if not path_str:
        return jsonify({"ok": False, "error": "Ścieżka nie może być pusta"}), 400
    p = Path(path_str)
    # Validate: try to create if doesn't exist
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Nie można utworzyć katalogu: {e}"}), 400
    with db_session() as db:
        _set_backup_dir(db, path_str)
    return jsonify({"ok": True})


@admin_bp.route("/api/admin/backup", methods=["POST"])
@role_required("admin")
def api_create_backup():
    with db_session() as db:
        backup_dir = _get_backup_dir(db)

    # Create timestamped folder
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    dest = backup_dir / f"lims_backup_{ts}"
    if dest.exists():
        return jsonify({"ok": False, "error": f"Backup {dest.name} już istnieje"}), 409

    try:
        dest.mkdir(parents=True, exist_ok=True)

        # 1. Backup database using VACUUM INTO for consistency
        dest_db = dest / "batch_db.sqlite"
        with db_session() as db:
            db.execute(f"VACUUM INTO ?", (str(dest_db),))

        # 2. Copy swiadectwa JSONs (skip PDFs, only .json)
        if SWIADECTWA_DIR.exists():
            dest_sw = dest / "swiadectwa"
            for json_file in SWIADECTWA_DIR.rglob("*.json"):
                rel = json_file.relative_to(SWIADECTWA_DIR)
                target = dest_sw / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(json_file, target)

    except Exception as e:
        # Clean up partial backup
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        return jsonify({"ok": False, "error": str(e)}), 500

    # Return info about created backup
    size_mb = dest_db.stat().st_size / (1024 * 1024) if dest_db.exists() else 0
    json_count = sum(1 for _ in dest.rglob("*.json"))
    return jsonify({
        "ok": True,
        "backup": {
            "name": dest.name,
            "size_mb": round(size_mb, 1),
            "json_count": json_count,
        },
    })


@admin_bp.route("/api/admin/backup/<name>", methods=["DELETE"])
@role_required("admin")
def api_delete_backup(name):
    if not name.startswith("lims_backup_"):
        return jsonify({"ok": False, "error": "Invalid backup name"}), 400
    with db_session() as db:
        backup_dir = _get_backup_dir(db)
    target = backup_dir / name
    if not target.exists():
        return jsonify({"ok": False, "error": "Nie znaleziono"}), 404
    shutil.rmtree(target)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

@admin_bp.route("/api/admin/feedback/<int:fb_id>/priorytet", methods=["PUT"])
@role_required("admin")
def api_feedback_priorytet(fb_id):
    data = request.get_json(silent=True) or {}
    priorytet = data.get("priorytet", "normal")
    if priorytet not in ("pilne", "normal"):
        return jsonify({"ok": False, "error": "Invalid priorytet"}), 400
    with db_session() as db:
        db.execute("UPDATE feedback SET priorytet=? WHERE id=?", (priorytet, fb_id))
        db.commit()
    return jsonify({"ok": True})


@admin_bp.route("/api/admin/feedback/<int:fb_id>", methods=["DELETE"])
@role_required("admin")
def api_feedback_delete(fb_id):
    with db_session() as db:
        db.execute("DELETE FROM feedback WHERE id=?", (fb_id,))
        db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# WiFi
# ---------------------------------------------------------------------------

@admin_bp.route("/api/admin/wifi/scan")
@role_required("admin")
def api_wifi_scan():
    """Scan available WiFi networks."""
    import subprocess
    try:
        out = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes"],
            capture_output=True, text=True, timeout=15,
        )
        networks = []
        seen = set()
        for line in out.stdout.strip().split("\n"):
            parts = line.split(":")
            if len(parts) >= 3 and parts[0] and parts[0] not in seen:
                seen.add(parts[0])
                networks.append({"ssid": parts[0], "signal": parts[1], "security": parts[2]})
        networks.sort(key=lambda n: int(n["signal"] or 0), reverse=True)
        return jsonify({"ok": True, "networks": networks})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/admin/wifi/connect", methods=["POST"])
@role_required("admin")
def api_wifi_connect():
    """Connect to a WiFi network."""
    import subprocess
    data = request.get_json(silent=True) or {}
    ssid = (data.get("ssid") or "").strip()
    password = (data.get("password") or "").strip()
    if not ssid:
        return jsonify({"ok": False, "error": "SSID wymagane"}), 400
    try:
        cmd = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            cmd += ["password", password]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return jsonify({"ok": True, "message": result.stdout.strip()})
        return jsonify({"ok": False, "error": result.stderr.strip() or result.stdout.strip()}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/admin/wifi/status")
@role_required("admin")
def api_wifi_status():
    """Get current WiFi connection status."""
    import subprocess
    try:
        out = subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE,STATE,CONNECTION", "device", "status"],
            capture_output=True, text=True, timeout=5,
        )
        for line in out.stdout.strip().split("\n"):
            parts = line.split(":")
            if len(parts) >= 3 and parts[0].startswith("wl"):
                return jsonify({"ok": True, "device": parts[0], "state": parts[1], "connection": parts[2] or None})
        return jsonify({"ok": True, "device": None, "state": "unavailable", "connection": None})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
