"""
models.py — Database helpers and user CRUD for MBR/EBR webapp.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import bcrypt

DB_PATH = Path(__file__).parent.parent / "data" / "batch_db_v4.sqlite"

PRODUCTS = ["Chegina_K7", "Chegina_K40GL", "Chegina_K40GLO", "Chegina_K40GLOL"]


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


# ---------------------------------------------------------------------------
# EBR Dashboard queries
# ---------------------------------------------------------------------------

def list_ebr_open(db: sqlite3.Connection) -> list[dict]:
    """List open EBR batches with last entry time and out-of-limit count."""
    rows = db.execute("""
        SELECT
            eb.ebr_id,
            eb.batch_id,
            eb.nr_partii,
            mt.produkt,
            eb.nr_amidatora,
            eb.dt_start,
            eb.status,
            (SELECT MAX(ew.dt_wpisu) FROM ebr_wyniki ew WHERE ew.ebr_id = eb.ebr_id)
                AS last_entry,
            (SELECT COUNT(*) FROM ebr_wyniki ew WHERE ew.ebr_id = eb.ebr_id AND ew.w_limicie = 0)
                AS out_of_limit
        FROM ebr_batches eb
        JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
        WHERE eb.status = 'open'
        ORDER BY eb.dt_start DESC
    """).fetchall()
    return [dict(r) for r in rows]


def list_ebr_completed(
    db: sqlite3.Connection, produkt: str | None = None, limit: int = 50
) -> list[dict]:
    """List completed batches, optionally filtered by produkt."""
    sql = """
        SELECT
            eb.ebr_id,
            eb.batch_id,
            eb.nr_partii,
            mt.produkt,
            eb.dt_end,
            (SELECT COUNT(*) FROM ebr_wyniki ew WHERE ew.ebr_id = eb.ebr_id AND ew.w_limicie = 0)
                AS out_of_limit
        FROM ebr_batches eb
        JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
        WHERE eb.status = 'completed'
    """
    params: list = []
    if produkt:
        sql += " AND mt.produkt = ?"
        params.append(produkt)
    sql += " ORDER BY eb.dt_end DESC LIMIT ?"
    params.append(limit)
    rows = db.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def export_wyniki_csv(
    db: sqlite3.Connection, produkt: str | None = None
) -> list[dict]:
    """Export all completed EBR wyniki for CSV download."""
    sql = """
        SELECT
            eb.batch_id,
            mt.produkt,
            eb.nr_partii,
            ew.sekcja,
            ew.kod_parametru,
            ew.tag,
            ew.wartosc,
            ew.min_limit,
            ew.max_limit,
            ew.w_limicie,
            ew.komentarz,
            ew.is_manual,
            ew.dt_wpisu,
            ew.wpisal
        FROM ebr_wyniki ew
        JOIN ebr_batches eb ON eb.ebr_id = ew.ebr_id
        JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
        WHERE eb.status = 'completed'
    """
    params: list = []
    if produkt:
        sql += " AND mt.produkt = ?"
        params.append(produkt)
    sql += " ORDER BY eb.batch_id, ew.sekcja, ew.kod_parametru"
    rows = db.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# EBR CRUD
# ---------------------------------------------------------------------------

def create_ebr(
    db: sqlite3.Connection,
    produkt: str,
    nr_partii: str,
    nr_amidatora: str,
    nr_mieszalnika: str,
    wielkosc_kg: float | None,
    operator: str,
) -> int | None:
    """Create new EBR from active MBR. Returns ebr_id or None if no active MBR."""
    mbr = get_active_mbr(db, produkt)
    if mbr is None:
        return None
    batch_id = f"{produkt}__{nr_partii.replace('/', '_')}"
    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, nr_amidatora, "
        "nr_mieszalnika, wielkosc_szarzy_kg, dt_start, operator) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (mbr["mbr_id"], batch_id, nr_partii, nr_amidatora,
         nr_mieszalnika, wielkosc_kg, now, operator),
    )
    db.commit()
    return cur.lastrowid


def get_ebr(db: sqlite3.Connection, ebr_id: int) -> dict | None:
    """Get EBR with joined MBR data (produkt, etapy_json, parametry_lab)."""
    row = db.execute("""
        SELECT
            eb.*,
            mt.produkt,
            mt.etapy_json,
            mt.parametry_lab
        FROM ebr_batches eb
        JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
        WHERE eb.ebr_id = ?
    """, (ebr_id,)).fetchone()
    return dict(row) if row else None


def get_ebr_wyniki(db: sqlite3.Connection, ebr_id: int) -> dict:
    """Returns {sekcja: {kod_parametru: row_dict}}."""
    rows = db.execute(
        "SELECT * FROM ebr_wyniki WHERE ebr_id = ?", (ebr_id,)
    ).fetchall()
    result: dict = {}
    for r in rows:
        d = dict(r)
        sek = d["sekcja"]
        kod = d["kod_parametru"]
        if sek not in result:
            result[sek] = {}
        result[sek][kod] = d
    return result


def save_wyniki(
    db: sqlite3.Connection,
    ebr_id: int,
    sekcja: str,
    values: dict,
    user: str,
) -> None:
    """Save lab results. values = {kod: {wartosc, komentarz}}.
    Looks up pole definition from MBR parametry_lab to get tag, min, max.
    Uses INSERT ... ON CONFLICT ... DO UPDATE for upsert.
    Auto-computes w_limicie."""
    ebr = get_ebr(db, ebr_id)
    if ebr is None:
        return
    parametry = json.loads(ebr["parametry_lab"]) if isinstance(ebr["parametry_lab"], str) else ebr["parametry_lab"]
    sekcja_def = parametry.get(sekcja, {})
    pola = sekcja_def.get("pola", []) if isinstance(sekcja_def, dict) else sekcja_def
    pola_map = {p["kod"]: p for p in pola}
    now = datetime.now().isoformat(timespec="seconds")

    for kod, entry in values.items():
        pole = pola_map.get(kod)
        if pole is None:
            continue
        wartosc_raw = entry.get("wartosc", "")
        komentarz = entry.get("komentarz", "")
        try:
            wartosc = float(wartosc_raw)
        except (ValueError, TypeError):
            continue

        tag = pole.get("tag", "")
        min_limit = pole.get("min")
        max_limit = pole.get("max")

        # Compute w_limicie
        w_limicie = 1
        if min_limit is not None and wartosc < min_limit:
            w_limicie = 0
        if max_limit is not None and wartosc > max_limit:
            w_limicie = 0

        db.execute("""
            INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc,
                min_limit, max_limit, w_limicie, komentarz, is_manual, dt_wpisu, wpisal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(ebr_id, sekcja, kod_parametru) DO UPDATE SET
                wartosc = excluded.wartosc,
                min_limit = excluded.min_limit,
                max_limit = excluded.max_limit,
                w_limicie = excluded.w_limicie,
                komentarz = excluded.komentarz,
                dt_wpisu = excluded.dt_wpisu,
                wpisal = excluded.wpisal
        """, (ebr_id, sekcja, kod, tag, wartosc, min_limit, max_limit,
              w_limicie, komentarz, now, user))
    db.commit()


def complete_ebr(db: sqlite3.Connection, ebr_id: int) -> None:
    """Set status='completed', dt_end=now."""
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "UPDATE ebr_batches SET status = 'completed', dt_end = ? WHERE ebr_id = ?",
        (now, ebr_id),
    )
    db.commit()


# ---------------------------------------------------------------------------
# V4 Sync
# ---------------------------------------------------------------------------

_KOD_TO_EVENT_COL = {
    "ph": "ph", "ph_10proc": "ph_10proc", "nd20": "nd20",
    "procent_sm": "procent_sm", "procent_sa": "procent_sa",
    "procent_nacl": "procent_nacl", "procent_aa": "procent_aa",
    "procent_so3": "procent_so3", "procent_h2o2": "procent_h2o2",
    "lk": "lk", "le_liczba_kwasowa": "lk",
    "barwa_fau": "barwa_fau", "barwa_hz": "barwa_hz",
}

_KOD_TO_AK_COL = {
    "ph": "ak_ph", "ph_10proc": "ak_ph_10proc", "nd20": "ak_nd20",
    "procent_sm": "ak_procent_sm", "procent_sa": "ak_procent_sa",
    "procent_nacl": "ak_procent_nacl", "procent_aa": "ak_procent_aa",
    "procent_so3": "ak_procent_so3", "procent_h2o2": "ak_procent_h2o2",
    "barwa_fau": "ak_barwa_fau", "barwa_hz": "ak_barwa_hz",
}

_SEKCJA_TO_STAGE = {
    "przed_standaryzacja": "standaryzacja",
    "analiza_koncowa": "analiza_koncowa",
}


def sync_ebr_to_v4(db: sqlite3.Connection, ebr_id: int) -> None:
    """Sync EBR data to v4 events and batch tables.
    1. Delete old digital events for this batch
    2. For each sekcja in wyniki: INSERT into events table
    3. If completed + has analiza_koncowa: UPSERT batch row with ak_* fields
    """
    ebr = get_ebr(db, ebr_id)
    if ebr is None:
        return
    batch_id = ebr["batch_id"]
    now = datetime.now().isoformat(timespec="seconds")

    # 0. Ensure batch row exists (required by FK on events)
    existing_batch = db.execute(
        "SELECT batch_id FROM batch WHERE batch_id = ?", (batch_id,)
    ).fetchone()
    if not existing_batch:
        db.execute(
            "INSERT INTO batch (batch_id, produkt, nr_partii, _source) VALUES (?, ?, ?, 'digital')",
            (batch_id, ebr["produkt"], ebr["nr_partii"]),
        )

    # 1. Delete old digital events for this batch
    db.execute(
        "DELETE FROM events WHERE batch_id = ? AND _source = 'digital'",
        (batch_id,),
    )

    # 2. Insert events for each sekcja
    wyniki = get_ebr_wyniki(db, ebr_id)
    seq = 0
    for sekcja, params in wyniki.items():
        stage = _SEKCJA_TO_STAGE.get(sekcja, sekcja)
        # Build column values from kod_parametru (maps to v4 event columns)
        col_values: dict = {}
        for kod, row in params.items():
            ecol = _KOD_TO_EVENT_COL.get(kod)
            if ecol and row["wartosc"] is not None:
                col_values[ecol] = row["wartosc"]

        if col_values:
            seq += 1
            cols = ["batch_id", "dt", "stage", "event_type", "seq", "_source", "_ts_precision"]
            vals = [batch_id, now, stage, "analiza", seq, "digital", "minute"]
            for c, v in col_values.items():
                cols.append(c)
                vals.append(v)
            placeholders = ", ".join(["?"] * len(vals))
            col_names = ", ".join(cols)
            db.execute(f"INSERT INTO events ({col_names}) VALUES ({placeholders})", vals)

    # 3. If completed + has analiza_koncowa: UPSERT batch row with ak_* fields
    if ebr["status"] == "completed" and "analiza_koncowa" in wyniki:
        ak_values: dict = {}
        for kod, row in wyniki["analiza_koncowa"].items():
            ak_col = _KOD_TO_AK_COL.get(kod)
            if ak_col and row["wartosc"] is not None:
                ak_values[ak_col] = row["wartosc"]

        if ak_values:
            # Check if batch row exists
            existing = db.execute(
                "SELECT batch_id FROM batch WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if existing:
                set_parts = [f"{c} = ?" for c in ak_values]
                vals = list(ak_values.values()) + [batch_id]
                db.execute(
                    f"UPDATE batch SET {', '.join(set_parts)} WHERE batch_id = ?",
                    vals,
                )
            else:
                # Insert new batch row
                cols = ["batch_id", "produkt", "nr_partii", "_source"]
                vals = [batch_id, ebr["produkt"], ebr["nr_partii"], "digital"]
                for c, v in ak_values.items():
                    cols.append(c)
                    vals.append(v)
                placeholders = ", ".join(["?"] * len(vals))
                col_names = ", ".join(cols)
                db.execute(
                    f"INSERT INTO batch ({col_names}) VALUES ({placeholders})", vals
                )

    db.commit()
