"""
technolog/models.py — MBR template CRUD helpers.
"""

import sqlite3
from datetime import datetime

from mbr.db import get_db, db_session  # noqa: F401
from mbr.shared.timezone import app_now_iso


def list_mbr(db: sqlite3.Connection) -> list[dict]:
    """Return all MBR templates ordered by produkt, then wersja descending."""
    rows = db.execute(
        "SELECT * FROM mbr_templates ORDER BY produkt, wersja DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_mbr(db: sqlite3.Connection, mbr_id: int) -> dict | None:
    """Return a single MBR template by ID, or None."""
    row = db.execute(
        "SELECT * FROM mbr_templates WHERE mbr_id = ?", (mbr_id,)
    ).fetchone()
    return dict(row) if row else None


def get_active_mbr(db: sqlite3.Connection, produkt: str) -> dict | None:
    """Return the active MBR template for a given product, or None."""
    row = db.execute(
        "SELECT * FROM mbr_templates WHERE produkt = ? AND status = 'active'",
        (produkt,),
    ).fetchone()
    return dict(row) if row else None


def save_mbr(
    db: sqlite3.Connection,
    mbr_id: int,
    etapy_json: str,
    parametry_lab: str,
    notatki: str,
) -> bool:
    """Update MBR template fields. Only allowed if status is 'draft'. Returns True on success."""
    row = db.execute(
        "SELECT status FROM mbr_templates WHERE mbr_id = ?", (mbr_id,)
    ).fetchone()
    if row is None or row["status"] != "draft":
        return False
    db.execute(
        "UPDATE mbr_templates SET etapy_json = ?, parametry_lab = ?, notatki = ? "
        "WHERE mbr_id = ?",
        (etapy_json, parametry_lab, notatki, mbr_id),
    )
    db.commit()
    return True


def activate_mbr(db: sqlite3.Connection, mbr_id: int) -> bool:
    """Activate a draft MBR: archive the current active one for the same product, then set this to active."""
    row = db.execute(
        "SELECT * FROM mbr_templates WHERE mbr_id = ?", (mbr_id,)
    ).fetchone()
    if row is None or row["status"] != "draft":
        return False
    produkt = row["produkt"]
    now = app_now_iso()
    # Archive current active template for same product
    db.execute(
        "UPDATE mbr_templates SET status = 'archived' "
        "WHERE produkt = ? AND status = 'active'",
        (produkt,),
    )
    # Activate the draft
    db.execute(
        "UPDATE mbr_templates SET status = 'active', dt_aktywacji = ? "
        "WHERE mbr_id = ?",
        (now, mbr_id),
    )
    db.commit()
    return True


def clone_mbr(db: sqlite3.Connection, mbr_id: int, user: str) -> int | None:
    """Clone an MBR template. New version = max version for that product + 1. Returns new mbr_id or None."""
    row = db.execute(
        "SELECT * FROM mbr_templates WHERE mbr_id = ?", (mbr_id,)
    ).fetchone()
    if row is None:
        return None
    produkt = row["produkt"]
    max_row = db.execute(
        "SELECT MAX(wersja) AS mv FROM mbr_templates WHERE produkt = ?",
        (produkt,),
    ).fetchone()
    new_wersja = (max_row["mv"] or 0) + 1
    now = app_now_iso()
    cur = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia, notatki) VALUES (?, ?, 'draft', ?, ?, ?, ?, ?)",
        (
            produkt,
            new_wersja,
            row["etapy_json"],
            row["parametry_lab"],
            user,
            now,
            None,
        ),
    )
    db.commit()
    return cur.lastrowid
