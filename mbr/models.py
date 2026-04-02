"""
models.py — Database helpers and user CRUD for MBR/EBR webapp.
"""

import sqlite3
from pathlib import Path

import bcrypt

DB_PATH = Path("data/batch_db_v4.sqlite")


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
