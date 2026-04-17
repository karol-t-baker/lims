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
    # Disk usage
    import shutil
    disk = shutil.disk_usage("/")
    disk_info = {
        "total_gb": round(disk.total / (1024**3), 1),
        "used_gb": round(disk.used / (1024**3), 1),
        "free_gb": round(disk.free / (1024**3), 1),
        "percent": round(disk.used / disk.total * 100),
    }
    return render_template(
        "admin/panel.html",
        backup_dir=str(backup_dir),
        backups=backups,
        feedback=feedback,
        disk=disk_info,
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

# ---------------------------------------------------------------------------
# Admin batch metadata editor — fix a mis-created szarża (wrong nastaw, typ,
# amidator, mieszalnik). Downstream effects of changing `typ` are handled by
# build_pipeline_context reading the live value on the next render.
# ---------------------------------------------------------------------------

_BATCH_META_FIELDS = ("nastaw", "typ", "nr_amidatora", "nr_mieszalnika")
_VALID_TYPY = ("szarza", "zbiornik", "platkowanie")


@admin_bp.route("/api/admin/ebr/<int:ebr_id>/meta", methods=["PATCH"])
@role_required("admin")
def api_admin_patch_batch_meta(ebr_id):
    from mbr.shared import audit

    data = request.get_json(silent=True) or {}
    patch = {k: data[k] for k in _BATCH_META_FIELDS if k in data}
    if not patch:
        return jsonify({"ok": False, "error": "no fields provided"}), 400

    if "typ" in patch and patch["typ"] not in _VALID_TYPY:
        return jsonify({"ok": False, "error": f"invalid typ (must be one of {_VALID_TYPY})"}), 400
    if "nastaw" in patch:
        try:
            nv = int(patch["nastaw"]) if patch["nastaw"] is not None else None
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "nastaw must be an integer"}), 400
        if nv is not None and nv <= 0:
            return jsonify({"ok": False, "error": "nastaw must be positive"}), 400
        patch["nastaw"] = nv

    with db_session() as db:
        current_cols = ", ".join(_BATCH_META_FIELDS)
        current = db.execute(
            f"SELECT {current_cols} FROM ebr_batches WHERE ebr_id=?",
            (ebr_id,),
        ).fetchone()
        if current is None:
            return jsonify({"ok": False, "error": "batch not found"}), 404

        old = {k: current[k] for k in _BATCH_META_FIELDS}
        new = {**old, **patch}
        diff = audit.diff_fields(old, new, list(patch.keys()))
        if not diff:
            return jsonify({"ok": True, "changed": False})

        set_sql = ", ".join(f"{k}=?" for k in patch.keys())
        db.execute(
            f"UPDATE ebr_batches SET {set_sql} WHERE ebr_id=?",
            (*patch.values(), ebr_id),
        )

        label_row = db.execute(
            "SELECT nr_partii FROM ebr_batches WHERE ebr_id=?", (ebr_id,),
        ).fetchone()
        audit.log_event(
            audit.EVENT_EBR_BATCH_UPDATED,
            entity_type="ebr",
            entity_id=ebr_id,
            entity_label=f"Szarża {label_row['nr_partii']}" if label_row else None,
            diff=diff,
            db=db,
        )
        db.commit()

    return jsonify({"ok": True, "changed": True, "diff": diff})


@admin_bp.route("/api/admin/ebr/<int:ebr_id>", methods=["DELETE"])
@role_required("admin")
def api_admin_delete_batch(ebr_id):
    """Hard-delete a szarża + cascade across child tables in one transaction.

    Only open/cancelled batches. Completed batches must be cancelled first —
    keeps the rail from wiping a finished szarża (certificates, sign-offs)
    by a misclick. The cert PDF files on disk are left alone; only the
    `swiadectwa` row goes.

    Audit emits EVENT_EBR_BATCH_DELETED with the freed nr_partii so the
    deletion is traceable even though the row is gone.
    """
    from mbr.shared import audit

    with db_session() as db:
        row = db.execute(
            "SELECT ebr_id, nr_partii, status, typ FROM ebr_batches WHERE ebr_id=?",
            (ebr_id,),
        ).fetchone()
        if row is None:
            return jsonify({"ok": False, "error": "batch not found"}), 404
        if row["status"] == "completed":
            return jsonify({
                "ok": False,
                "error": "nie można usunąć ukończonej szarży — anuluj ją najpierw",
            }), 400

        nr_partii = row["nr_partii"]
        status = row["status"]

        # Child wipe-out order: deepest refs first.
        db.execute(
            "DELETE FROM ebr_korekta_v2 WHERE sesja_id IN "
            "(SELECT id FROM ebr_etap_sesja WHERE ebr_id=?)",
            (ebr_id,),
        )
        db.execute(
            "DELETE FROM ebr_pomiar WHERE sesja_id IN "
            "(SELECT id FROM ebr_etap_sesja WHERE ebr_id=?)",
            (ebr_id,),
        )
        db.execute("DELETE FROM ebr_etap_sesja WHERE ebr_id=?", (ebr_id,))
        db.execute("DELETE FROM ebr_wyniki WHERE ebr_id=?", (ebr_id,))
        db.execute("DELETE FROM ebr_uwagi_history WHERE ebr_id=?", (ebr_id,))
        try:
            db.execute("DELETE FROM platkowanie_substraty WHERE ebr_id=?", (ebr_id,))
        except Exception:
            pass  # table may not exist on minimal test DBs
        try:
            db.execute("DELETE FROM swiadectwa WHERE ebr_id=?", (ebr_id,))
        except Exception:
            pass

        audit.log_event(
            audit.EVENT_EBR_BATCH_DELETED,
            entity_type="ebr",
            entity_id=ebr_id,
            entity_label=f"Szarża {nr_partii}" if nr_partii else f"EBR #{ebr_id}",
            payload={"nr_partii": nr_partii, "status": status, "typ": row["typ"]},
            db=db,
        )

        db.execute("DELETE FROM ebr_batches WHERE ebr_id=?", (ebr_id,))
        db.commit()

    return jsonify({"ok": True, "nr_partii": nr_partii})


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


@admin_bp.route("/api/admin/feedback/export", methods=["GET"])
@role_required("admin")
def api_feedback_export():
    with db_session() as db:
        rows = db.execute("SELECT * FROM feedback ORDER BY dt DESC").fetchall()
        data = [dict(r) for r in rows]
    resp = jsonify(data)
    resp.headers["Content-Disposition"] = "attachment; filename=feedback.json"
    return resp


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

@admin_bp.route("/api/admin/cert.crt")
def api_download_cert():
    """Download SSL certificate for browser trust (no login required)."""
    from flask import send_file
    cert_path = "/etc/ssl/lims/lims.crt"
    return send_file(cert_path, mimetype="application/x-x509-ca-cert",
                     as_attachment=True, download_name="labcore.crt")


@admin_bp.route("/api/admin/db-snapshot")
def api_db_snapshot():
    """Download current DB as file (for COA app sync). No login required — LAN only."""
    from flask import send_file
    from mbr.db import DB_PATH
    return send_file(str(DB_PATH), mimetype="application/octet-stream",
                     as_attachment=True, download_name="batch_db.sqlite")


@admin_bp.route("/api/completed")
def api_completed():
    """Return completed batches with sync_seq > since.
<<<<<<< HEAD

    Query params:
        since (int): last known sync_seq (default 0 = return all)
        ref_hash (str): client's reference table hash (optional)
    """
    import hashlib
    since = request.args.get("since", 0, type=int)
    client_ref_hash = request.args.get("ref_hash", "")

    with db_session() as db:
        # Reference tables (same hash logic as existing sync)
        ref_counts = (
            str(db.execute("SELECT COUNT(*) FROM parametry_analityczne").fetchone()[0]) +
            str(db.execute("SELECT COUNT(*) FROM metody_miareczkowe").fetchone()[0]) +
            str(db.execute("SELECT COUNT(*) FROM workers").fetchone()[0]) +
            str(db.execute("SELECT COUNT(*) FROM mbr_templates").fetchone()[0])
        )
        ref_hash = hashlib.md5(ref_counts.encode()).hexdigest()[:8]

        reference = None
        if client_ref_hash != ref_hash:
            reference = {
                "parametry_analityczne": [dict(r) for r in db.execute("SELECT * FROM parametry_analityczne").fetchall()],
                "metody_miareczkowe": [dict(r) for r in db.execute("SELECT * FROM metody_miareczkowe").fetchall()],
                "workers": [dict(r) for r in db.execute("SELECT * FROM workers").fetchall()],
                "mbr_templates": [dict(r) for r in db.execute("SELECT * FROM mbr_templates").fetchall()],
            }

        # Batches with sync_seq > since
        batches = [dict(r) for r in db.execute(
            "SELECT * FROM ebr_batches WHERE status='completed' AND sync_seq > ? ORDER BY sync_seq",
            (since,),
        ).fetchall()]

        batch_ids = [b["ebr_id"] for b in batches]
        wyniki = []
        swiadectwa = []
        if batch_ids:
            placeholders = ",".join("?" * len(batch_ids))
            wyniki = [dict(r) for r in db.execute(
                f"SELECT * FROM ebr_wyniki WHERE ebr_id IN ({placeholders})", batch_ids
            ).fetchall()]
            swiadectwa = [dict(r) for r in db.execute(
                f"SELECT * FROM swiadectwa WHERE ebr_id IN ({placeholders})", batch_ids
            ).fetchall()]

        max_seq = db.execute(
            "SELECT COALESCE(MAX(sync_seq), 0) FROM ebr_batches WHERE status='completed'"
        ).fetchone()[0]

        total_completed = db.execute(
            "SELECT COUNT(*) FROM ebr_batches WHERE status='completed'"
        ).fetchone()[0]

    return jsonify({
        "ok": True,
        "since": since,
        "max_seq": max_seq,
        "ref_hash": ref_hash,
        "reference": reference,
        "batches": batches,
        "wyniki": wyniki,
        "swiadectwa": swiadectwa,
        "total_completed": total_completed,
    })




@admin_bp.route("/api/admin/wifi/scan")
@role_required("admin")
def api_wifi_scan():
    """Scan available WiFi networks."""
    import subprocess
    try:
        out = subprocess.run(
            ["sudo", "nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes"],
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
        cmd = ["sudo", "nmcli", "device", "wifi", "connect", ssid]
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
            ["sudo", "nmcli", "-t", "-f", "DEVICE,STATE,CONNECTION", "device", "status"],
            capture_output=True, text=True, timeout=5,
        )
        for line in out.stdout.strip().split("\n"):
            parts = line.split(":")
            if len(parts) >= 3 and parts[0].startswith("wl"):
                return jsonify({"ok": True, "device": parts[0], "state": parts[1], "connection": parts[2] or None})
        return jsonify({"ok": True, "device": None, "state": "unavailable", "connection": None})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
