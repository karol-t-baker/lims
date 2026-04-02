"""
models.py — Database helpers and user CRUD for MBR/EBR webapp.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import bcrypt

DB_PATH = Path(__file__).parent.parent / "data" / "batch_db_v4.sqlite"


def get_db() -> sqlite3.Connection:
    """Return sqlite3 connection with Row factory and foreign_keys=ON."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_mbr_tables(db: sqlite3.Connection) -> None:
    """Create MBR/EBR tables if they don't exist."""
    db.executescript("""
        CREATE TABLE IF NOT EXISTS mbr_users (
            user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            login           TEXT UNIQUE NOT NULL,
            password_hash   TEXT NOT NULL,
            rola            TEXT NOT NULL CHECK(rola IN ('technolog', 'laborant')),
            imie_nazwisko   TEXT
        );

        CREATE TABLE IF NOT EXISTS mbr_templates (
            mbr_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            produkt         TEXT NOT NULL,
            wersja          INTEGER NOT NULL DEFAULT 1,
            status          TEXT NOT NULL DEFAULT 'draft'
                            CHECK(status IN ('draft', 'active', 'archived')),
            etapy_json      TEXT NOT NULL DEFAULT '[]',
            parametry_lab   TEXT NOT NULL DEFAULT '{}',
            utworzony_przez  TEXT,
            dt_utworzenia    TEXT NOT NULL,
            dt_aktywacji    TEXT,
            notatki         TEXT,
            UNIQUE(produkt, wersja)
        );

        CREATE TABLE IF NOT EXISTS ebr_batches (
            ebr_id              INTEGER PRIMARY KEY AUTOINCREMENT,
            mbr_id              INTEGER NOT NULL REFERENCES mbr_templates(mbr_id),
            batch_id            TEXT UNIQUE NOT NULL,
            nr_partii           TEXT NOT NULL,
            nr_amidatora        TEXT,
            nr_mieszalnika      TEXT,
            wielkosc_szarzy_kg  REAL,
            surowce_json        TEXT,
            dt_start            TEXT NOT NULL,
            dt_end              TEXT,
            status              TEXT NOT NULL DEFAULT 'open'
                                CHECK(status IN ('open', 'completed', 'cancelled')),
            operator            TEXT
        );

        CREATE TABLE IF NOT EXISTS ebr_wyniki (
            wynik_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ebr_id          INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
            sekcja          TEXT NOT NULL,
            kod_parametru   TEXT NOT NULL,
            tag             TEXT NOT NULL,
            wartosc         REAL,
            min_limit       REAL,
            max_limit       REAL,
            w_limicie       INTEGER,
            komentarz       TEXT,
            is_manual       INTEGER NOT NULL DEFAULT 1,
            dt_wpisu        TEXT NOT NULL,
            wpisal          TEXT NOT NULL,
            UNIQUE(ebr_id, sekcja, kod_parametru)
        );
    """)
    db.commit()


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

def create_user(
    db: sqlite3.Connection,
    login: str,
    password: str,
    rola: str,
    imie_nazwisko: str | None = None,
) -> int:
    """Create a new user with bcrypt-hashed password. Returns user_id."""
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    cur = db.execute(
        "INSERT INTO mbr_users (login, password_hash, rola, imie_nazwisko) "
        "VALUES (?, ?, ?, ?)",
        (login, password_hash, rola, imie_nazwisko),
    )
    db.commit()
    return cur.lastrowid


def verify_user(db: sqlite3.Connection, login: str, password: str) -> dict | None:
    """Verify credentials. Returns user row as dict or None."""
    row = db.execute(
        "SELECT * FROM mbr_users WHERE login = ?", (login,)
    ).fetchone()
    if row is None:
        return None
    if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# MBR CRUD
# ---------------------------------------------------------------------------

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
    now = datetime.now().isoformat(timespec="seconds")
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
    now = datetime.now().isoformat(timespec="seconds")
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
