"""
models.py — Database helpers and user CRUD for MBR/EBR webapp.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import bcrypt

DB_PATH = Path(__file__).parent.parent / "data" / "batch_db_v4.sqlite"

PRODUCTS = [
    # Grupa 1: Chegina betainy (2 sekcje lab)
    "Chegina_K40GL", "Chegina_K40GLO", "Chegina_K40GLOL", "Chegina_K7",
    # Grupa 2: Pozostałe Cheginy
    "Chegina_K40GLOS", "Chegina_K40GLOL_HQ", "Chegina_K7GLO", "Chegina_K7B",
    "Chegina_KK", "Chegina_CC", "Chegina_CCR", "Chegina_L9", "Chegina",
    # Grupa 3: Cheminoxy
    "Cheminox_K", "Cheminox_K35", "Cheminox_LA",
    # Grupa 4: Chemipole
    "Chemipol_ML", "Chemipol_OL",
    # Grupa 5: Monamidy
    "Monamid_KO", "Monamid_KO_Revada", "Monamid_K", "Monamid_L", "Monamid_S",
    # Grupa 6: Distery i Monestery
    "Dister_E", "Monester_O", "Monester_S",
    # Grupa 7: Alkinole i Alstermidy
    "Alkinol", "Alstermid_K", "Alstermid",
    # Grupa 8: Chemale
    "Chemal_CS3070", "Chemal_EO20", "Chemal_SE12", "Chemal_PC",
    # Grupa 9: Inne
    "Polcet_A", "Chelamid_DK", "Glikoster_P", "Citrowax",
    "Kwas_stearynowy", "Perlico_45", "SLES", "HSH_CS3070",
]


def get_db() -> sqlite3.Connection:
    """Return sqlite3 connection with Row factory and foreign_keys=ON."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


@contextmanager
def db_session():
    db = get_db()
    try:
        yield db
    finally:
        db.close()


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
            operator            TEXT,
            typ                 TEXT NOT NULL DEFAULT 'szarza'
                                CHECK(typ IN ('szarza', 'zbiornik'))
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
    db.execute("CREATE INDEX IF NOT EXISTS idx_wyniki_ebr_limicie ON ebr_wyniki(ebr_id, w_limicie, dt_wpisu)")
    db.commit()

    # Migration: add typ column if missing (SQLite doesn't support ALTER TABLE ADD with CHECK)
    try:
        db.execute("ALTER TABLE ebr_batches ADD COLUMN typ TEXT NOT NULL DEFAULT 'szarza'")
        db.commit()
    except Exception:
        pass  # column already exists

    # Migration: add samples_json column for titration persistence
    try:
        db.execute("ALTER TABLE ebr_wyniki ADD COLUMN samples_json TEXT")
        db.commit()
    except Exception:
        pass  # column already exists


# ---------------------------------------------------------------------------
# Auto-numbering
# ---------------------------------------------------------------------------

def next_nr_partii(db: sqlite3.Connection, produkt: str) -> str:
    """Get next available nr_partii for a product in current year.
    Checks both ebr_batches AND v4 batch table for highest number.
    Returns e.g. '57/2026'."""
    year = datetime.now().year
    suffix = f"/{year}"

    # Check ebr_batches and v4 batch table (both underscore and space variants)
    rows = db.execute("""
        SELECT nr_partii FROM ebr_batches
        WHERE batch_id LIKE ? AND nr_partii LIKE ?
        UNION ALL
        SELECT nr_partii FROM batch
        WHERE (produkt = ? OR produkt = ?) AND nr_partii LIKE ?
    """, (f"{produkt}%", f"%{suffix}",
          produkt, produkt.replace('_', ' '), f"%{suffix}")).fetchall()

    max_num = 0
    for r in rows:
        try:
            num = int(r["nr_partii"].split("/")[0])
            if num > max_num:
                max_num = num
        except (ValueError, IndexError):
            pass

    return f"{max_num + 1}/{year}"


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

def list_ebr_open(
    db: sqlite3.Connection, produkt: str | None = None, typ: str | None = None
) -> list[dict]:
    """List open EBR batches with last entry time, out-of-limit count, and stage info."""
    sql = """
        SELECT
            eb.ebr_id,
            eb.batch_id,
            eb.nr_partii,
            mt.produkt,
            eb.nr_amidatora,
            eb.nr_mieszalnika,
            eb.dt_start,
            eb.status,
            eb.typ,
            mt.parametry_lab,
            (SELECT MAX(ew.dt_wpisu) FROM ebr_wyniki ew WHERE ew.ebr_id = eb.ebr_id)
                AS last_entry,
            (SELECT COUNT(*) FROM ebr_wyniki ew WHERE ew.ebr_id = eb.ebr_id AND ew.w_limicie = 0)
                AS out_of_limit,
            (SELECT COUNT(*) FROM ebr_wyniki ew WHERE ew.ebr_id = eb.ebr_id AND ew.wartosc IS NOT NULL)
                AS filled_count
        FROM ebr_batches eb
        JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
        WHERE eb.status = 'open'
    """
    params: list = []
    if produkt:
        sql += " AND mt.produkt = ?"
        params.append(produkt)
    if typ:
        sql += " AND eb.typ = ?"
        params.append(typ)
    sql += " ORDER BY eb.dt_start DESC"
    rows = db.execute(sql, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d.update(_compute_stage_info(d))
        d.pop("parametry_lab", None)  # don't send raw JSON to templates
        result.append(d)
    return result


def _compute_stage_info(ebr_row: dict) -> dict:
    """Compute synthesis stage from completed lab sections.
    Supports new cyclic (analiza+standaryzacja), legacy (przed+koncowa), and simple schemas.
    """
    parametry_raw = ebr_row.get("parametry_lab", "{}")
    parametry = json.loads(parametry_raw) if isinstance(parametry_raw, str) else parametry_raw
    filled = ebr_row.get("filled_count", 0) or 0
    typ = ebr_row.get("typ", "szarza")

    sections = {}
    total_fields = 0
    for sek_key, sek_def in parametry.items():
        pola = sek_def.get("pola", sek_def) if isinstance(sek_def, dict) else sek_def
        if not isinstance(pola, list):
            pola = []
        n = len(pola)
        total_fields += n
        sections[sek_key] = n

    if total_fields == 0:
        return {"stage_name": "Brak parametrów", "stage_status": "waiting", "progress_pct": 0}

    # Zbiornik
    if typ == "zbiornik":
        if filled == 0:
            return {"stage_name": "Analiza końcowa", "stage_status": "waiting", "progress_pct": 0}
        elif filled < total_fields:
            return {"stage_name": "Analiza końcowa", "stage_status": "in_progress", "progress_pct": round((filled / total_fields) * 100)}
        else:
            return {"stage_name": "Gotowy do zatwierdzenia", "stage_status": "done", "progress_pct": 100}

    # New cyclic schema: analiza + dodatki
    analiza_n = sections.get("analiza", 0)
    dodatki_n = sections.get("dodatki", 0)

    if analiza_n > 0 and dodatki_n > 0:
        # Standaryzacja etap = analiza + dodatki, then Analiza końcowa = analiza again
        # One full cycle: analiza_n + dodatki_n + analiza_n fields
        first_stand = analiza_n + dodatki_n  # standaryzacja phase (analysis + additives)
        if filled == 0:
            return {"stage_name": "Standaryzacja", "stage_status": "waiting", "progress_pct": 0}
        elif filled < first_stand:
            return {"stage_name": "Standaryzacja", "stage_status": "in_progress", "progress_pct": round((filled / first_stand) * 50)}
        else:
            # Past first standaryzacja → in analiza końcowa or correction cycles
            past_stand = filled - first_stand
            correction_size = dodatki_n + analiza_n  # each correction = new additives + new analysis
            if past_stand == 0:
                return {"stage_name": "Analiza końcowa", "stage_status": "waiting", "progress_pct": 60}
            pos_in_correction = past_stand % correction_size if correction_size > 0 else 0
            if pos_in_correction == 0 and past_stand > 0:
                # Just completed a full correction cycle → waiting for decision/next analiza końcowa
                return {"stage_name": "Analiza końcowa", "stage_status": "waiting", "progress_pct": 60}
            if pos_in_correction <= analiza_n:
                # Filling analiza końcowa
                return {"stage_name": "Analiza końcowa", "stage_status": "in_progress", "progress_pct": 75}
            else:
                # Filling correction additives (standaryzacja phase)
                return {"stage_name": "Standaryzacja", "stage_status": "in_progress", "progress_pct": 50}

    # Legacy: przed_standaryzacja + analiza_koncowa
    przed_n = sections.get("przed_standaryzacja", 0)
    konc_n = sections.get("analiza_koncowa", 0)

    if przed_n > 0:
        progress_pct = round((filled / (przed_n + konc_n)) * 100) if (przed_n + konc_n) > 0 else 0
        if filled == 0:
            return {"stage_name": "Przed standaryzacją", "stage_status": "waiting", "progress_pct": 0}
        if filled < przed_n:
            return {"stage_name": "Analiza przed standaryzacją", "stage_status": "in_progress", "progress_pct": progress_pct}
        if filled == przed_n:
            return {"stage_name": "Standaryzacja", "stage_status": "waiting", "progress_pct": progress_pct}
        filled_konc = filled - przed_n
        if filled_konc < konc_n:
            return {"stage_name": "Analiza końcowa", "stage_status": "in_progress", "progress_pct": progress_pct}
        return {"stage_name": "Gotowy do zatwierdzenia", "stage_status": "done", "progress_pct": 100}

    # Simple: only analiza_koncowa
    if filled == 0:
        return {"stage_name": "Analiza końcowa", "stage_status": "waiting", "progress_pct": 0}
    elif filled < total_fields:
        return {"stage_name": "Analiza końcowa", "stage_status": "in_progress", "progress_pct": round((filled / total_fields) * 100)}
    return {"stage_name": "Gotowy do zatwierdzenia", "stage_status": "done", "progress_pct": 100}


def list_ebr_completed(
    db: sqlite3.Connection, produkt: str | None = None, typ: str | None = None, limit: int = 50
) -> list[dict]:
    """List completed batches, optionally filtered by produkt and typ."""
    sql = """
        SELECT
            eb.ebr_id,
            eb.batch_id,
            eb.nr_partii,
            mt.produkt,
            eb.dt_end,
            eb.typ,
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
    if typ:
        sql += " AND eb.typ = ?"
        params.append(typ)
    sql += " ORDER BY eb.dt_end DESC LIMIT ?"
    params.append(limit)
    rows = db.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def list_ebr_recent(db: sqlite3.Connection, days: int = 7) -> list[dict]:
    """List recently completed batches (last N days) with wyniki summary."""
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    rows = db.execute("""
        SELECT
            eb.ebr_id,
            eb.batch_id,
            eb.nr_partii,
            mt.produkt,
            eb.nr_amidatora,
            eb.dt_start,
            eb.dt_end,
            eb.typ,
            (SELECT COUNT(*) FROM ebr_wyniki ew WHERE ew.ebr_id = eb.ebr_id AND ew.w_limicie = 0)
                AS out_of_limit,
            (SELECT COUNT(*) FROM ebr_wyniki ew WHERE ew.ebr_id = eb.ebr_id)
                AS total_wyniki
        FROM ebr_batches eb
        JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
        WHERE eb.status = 'completed' AND eb.dt_end >= ?
        ORDER BY eb.dt_end DESC
    """, (cutoff,)).fetchall()
    return [dict(r) for r in rows]


def list_completed_registry(
    db: sqlite3.Connection, produkt: str | None = None, limit: int = 100
) -> list[dict]:
    """Get completed batches with all wyniki for registry table view."""
    sql = """
        SELECT eb.ebr_id, eb.batch_id, eb.nr_partii, mt.produkt, eb.dt_end, eb.typ
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

    result = []
    for r in rows:
        d = dict(r)
        wyniki = db.execute(
            "SELECT kod_parametru, tag, wartosc, w_limicie FROM ebr_wyniki WHERE ebr_id = ?",
            (d["ebr_id"],)
        ).fetchall()
        d["wyniki"] = {w["kod_parametru"]: dict(w) for w in wyniki}
        result.append(d)
    return result


def get_registry_columns(db: sqlite3.Connection, produkt: str) -> list:
    """Get column definitions (parameter names + limits) for a product's registry table."""
    mbr = db.execute(
        "SELECT parametry_lab FROM mbr_templates WHERE produkt = ? AND status = 'active'",
        (produkt,)
    ).fetchone()
    if not mbr:
        return []
    parametry = json.loads(mbr["parametry_lab"]) if isinstance(mbr["parametry_lab"], str) else mbr["parametry_lab"]
    # New cyclic schema uses "analiza", legacy uses "analiza_koncowa"
    sekcja = parametry.get("analiza") or parametry.get("analiza_koncowa", {})
    pola = sekcja.get("pola", sekcja) if isinstance(sekcja, dict) else sekcja
    if not isinstance(pola, list):
        return []
    return pola


def list_completed_products(db: sqlite3.Connection) -> list[str]:
    """Get list of all products that have at least one completed batch."""
    rows = db.execute("""
        SELECT DISTINCT mt.produkt
        FROM ebr_batches eb
        JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
        WHERE eb.status = 'completed'
        ORDER BY mt.produkt
    """).fetchall()
    return [r["produkt"] for r in rows]


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
    typ: str = 'szarza',
) -> int | None:
    """Create new EBR from active MBR. Returns ebr_id or None if no active MBR."""
    mbr = get_active_mbr(db, produkt)
    if mbr is None:
        return None
    batch_id = f"{produkt}__{nr_partii.replace('/', '_')}"
    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, nr_amidatora, "
        "nr_mieszalnika, wielkosc_szarzy_kg, dt_start, operator, typ) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (mbr["mbr_id"], batch_id, nr_partii, nr_amidatora,
         nr_mieszalnika, wielkosc_kg, now, operator, typ),
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


def get_round_state(wyniki: dict) -> dict:
    """Compute current round state from wyniki keyed by sekcja.

    Cyclic flow: analiza__1 → dodatki__1 → analiza__2 → [dodatki__2 → analiza__3 → ...]
    Etap Standaryzacja = analiza + dodatki. Etap Analiza końcowa = analiza (runda >= 2).

    Returns:
        {
            "last_analiza": int,    # highest N from analiza__N (0 if none)
            "last_dodatki": int,    # highest N from dodatki__N (0 if none)
            "next_step": str,       # "analiza"|"dodatki"
            "next_sekcja": str,     # e.g. "analiza__1" or "dodatki__1"
            "is_decision": bool,    # True when analiza końcowa done (runda >= 2, no pending dodatki)
            "prev_analiza_out": list,  # kods out of limit in last analiza
        }
    """
    last_a = 0
    last_d = 0
    for sek in wyniki:
        if sek.startswith("analiza__"):
            n = int(sek.split("__")[1])
            if n > last_a:
                last_a = n
        elif sek.startswith("dodatki__"):
            n = int(sek.split("__")[1])
            if n > last_d:
                last_d = n
        # Legacy support
        elif sek == "przed_standaryzacja":
            last_a = max(last_a, 1)
        elif sek == "analiza_koncowa":
            last_a = max(last_a, 2)

    # Determine next step
    if last_a == 0:
        next_step = "analiza"
        next_sekcja = "analiza__1"
    elif last_a > last_d:
        # Analiza done, waiting for additives
        next_step = "dodatki"
        next_sekcja = f"dodatki__{last_a}"
    else:
        # Additives done, waiting for next analiza (= analiza końcowa)
        next_step = "analiza"
        next_sekcja = f"analiza__{last_d + 1}"

    # Decision: analiza końcowa just completed (runda >= 2, awaiting decision)
    is_decision = last_a > 1 and last_a > last_d

    # Find kods out of limit in most recent analiza
    prev_out = []
    if last_a > 0:
        last_analiza_key = f"analiza__{last_a}"
        if last_analiza_key not in wyniki:
            if last_a == 1 and "przed_standaryzacja" in wyniki:
                last_analiza_key = "przed_standaryzacja"
            elif last_a == 2 and "analiza_koncowa" in wyniki:
                last_analiza_key = "analiza_koncowa"
        sek_wyniki = wyniki.get(last_analiza_key, {})
        for kod, row in sek_wyniki.items():
            if row.get("w_limicie") == 0:
                prev_out.append(kod)

    return {
        "last_analiza": last_a,
        "last_dodatki": last_d,
        "next_step": next_step,
        "next_sekcja": next_sekcja,
        "is_decision": is_decision,
        "prev_analiza_out": prev_out,
    }


def save_wyniki(
    db: sqlite3.Connection,
    ebr_id: int,
    sekcja: str,
    values: dict,
    user: str,
    ebr: dict | None = None,
) -> None:
    """Save lab results. values = {kod: {wartosc, komentarz}}.
    Looks up pole definition from MBR parametry_lab to get tag, min, max.
    Uses INSERT ... ON CONFLICT ... DO UPDATE for upsert.
    Auto-computes w_limicie."""
    if ebr is None:
        ebr = get_ebr(db, ebr_id)
    if ebr is None:
        return
    parametry = json.loads(ebr["parametry_lab"]) if isinstance(ebr["parametry_lab"], str) else ebr["parametry_lab"]
    # Resolve base sekcja: "analiza__2" → "analiza", "analiza_koncowa" → "analiza_koncowa"
    base_sekcja = sekcja.split("__")[0] if "__" in sekcja else sekcja
    sekcja_def = parametry.get(base_sekcja, {})
    pola = sekcja_def.get("pola", []) if isinstance(sekcja_def, dict) else sekcja_def
    if not isinstance(pola, list):
        pola = []
    pola_map = {p["kod"]: p for p in pola if isinstance(p, dict) and "kod" in p}
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
                -- samples_json intentionally NOT overwritten here
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
    "sm": "procent_sm", "sa": "procent_sa",
    "nacl": "procent_nacl", "aa": "procent_aa",
    "so3": "procent_so3", "h2o2": "procent_h2o2",
    "lk": "lk", "le_liczba_kwasowa": "lk",
    "barwa_fau": "barwa_fau", "barwa_hz": "barwa_hz",
    "gestosc": "gestosc",
    # Legacy kods (procent_ prefix from old OCR data)
    "procent_sm": "procent_sm", "procent_sa": "procent_sa",
    "procent_nacl": "procent_nacl", "procent_aa": "procent_aa",
    "procent_so3": "procent_so3", "procent_h2o2": "procent_h2o2",
    # Standaryzacja additives
    "kwas_kg": "kwas_kg", "woda_kg": "woda_kg", "nacl_kg": "nacl_kg",
}

_KOD_TO_AK_COL = {
    "ph": "ak_ph", "ph_10proc": "ak_ph_10proc", "nd20": "ak_nd20",
    "sm": "ak_procent_sm", "sa": "ak_procent_sa",
    "nacl": "ak_procent_nacl", "aa": "ak_procent_aa",
    "so3": "ak_procent_so3", "h2o2": "ak_procent_h2o2",
    "barwa_fau": "ak_barwa_fau", "barwa_hz": "ak_barwa_hz",
    # Legacy kods
    "procent_sm": "ak_procent_sm", "procent_sa": "ak_procent_sa",
    "procent_nacl": "ak_procent_nacl", "procent_aa": "ak_procent_aa",
    "procent_so3": "ak_procent_so3", "procent_h2o2": "ak_procent_h2o2",
}


def sync_ebr_to_v4(db: sqlite3.Connection, ebr_id: int, ebr: dict | None = None) -> None:
    """Sync EBR data to v4 events and batch tables.
    Handles round-suffixed sekcjas (analiza__1, standaryzacja__2)
    and legacy sekcjas (przed_standaryzacja, analiza_koncowa).
    """
    if ebr is None:
        ebr = get_ebr(db, ebr_id)
    if ebr is None:
        return
    batch_id = ebr["batch_id"]
    now = datetime.now().isoformat(timespec="seconds")

    # 0. Ensure batch row exists
    existing_batch = db.execute(
        "SELECT batch_id FROM batch WHERE batch_id = ?", (batch_id,)
    ).fetchone()
    if not existing_batch:
        db.execute(
            "INSERT INTO batch (batch_id, produkt, nr_partii, _source) VALUES (?, ?, ?, 'digital')",
            (batch_id, ebr["produkt"], ebr["nr_partii"]),
        )

    # 1. Delete old digital events
    db.execute(
        "DELETE FROM events WHERE batch_id = ? AND _source = 'digital'",
        (batch_id,),
    )

    # 2. Insert events for each sekcja
    wyniki = get_ebr_wyniki(db, ebr_id)
    seq = 0

    def _sekcja_sort_key(item: tuple) -> tuple:
        """Sort sekcjas in round-interleaved order: analiza__1, dodatki__1, analiza__2, ..."""
        sek = item[0]
        if sek.startswith("analiza__"):
            n = int(sek.split("__")[1])
            return (n, 0, sek)
        if sek.startswith("dodatki__"):
            n = int(sek.split("__")[1])
            return (n, 1, sek)
        # Legacy / other: append at end in alphabetical order
        return (9999, 0, sek)

    for sekcja, params in sorted(wyniki.items(), key=_sekcja_sort_key):
        # Derive stage and runda from sekcja key
        if "__" in sekcja:
            base, runda_str = sekcja.split("__", 1)
            runda = int(runda_str)
        else:
            base = sekcja
            runda = None

        # Map base sekcja to event stage
        if base == "analiza":
            stage = "analiza"
        elif base == "dodatki":
            stage = "standaryzacja"
        elif base == "przed_standaryzacja":
            stage = "standaryzacja"
            runda = 1
        elif base == "analiza_koncowa":
            stage = "analiza_koncowa"
        else:
            stage = base

        event_type = "dodatek" if base == "dodatki" else "analiza"

        col_values: dict = {}
        for kod, row in params.items():
            ecol = _KOD_TO_EVENT_COL.get(kod)
            if ecol and row["wartosc"] is not None:
                col_values[ecol] = row["wartosc"]

        if col_values:
            seq += 1
            cols = ["batch_id", "dt", "stage", "event_type", "seq", "_source", "_ts_precision"]
            vals = [batch_id, now, stage, event_type, seq, "digital", "minute"]
            if runda is not None:
                cols.append("runda")
                vals.append(runda)
            for c, v in col_values.items():
                cols.append(c)
                vals.append(v)
            placeholders = ", ".join(["?"] * len(vals))
            col_names = ", ".join(cols)
            db.execute(f"INSERT INTO events ({col_names}) VALUES ({placeholders})", vals)

    # 3. If completed: find last analiza round → update ak_* fields
    if ebr["status"] == "completed":
        last_analiza_key = None
        max_n = 0
        for sek in wyniki:
            if sek.startswith("analiza__"):
                n = int(sek.split("__")[1])
                if n > max_n:
                    max_n = n
                    last_analiza_key = sek
            elif sek == "analiza_koncowa":
                last_analiza_key = sek

        if last_analiza_key and last_analiza_key in wyniki:
            ak_values: dict = {}
            for kod, row in wyniki[last_analiza_key].items():
                ak_col = _KOD_TO_AK_COL.get(kod)
                if ak_col and row["wartosc"] is not None:
                    ak_values[ak_col] = row["wartosc"]

            if ak_values:
                set_parts = [f"{c} = ?" for c in ak_values]
                vals = list(ak_values.values()) + [batch_id]
                db.execute(
                    f"UPDATE batch SET {', '.join(set_parts)} WHERE batch_id = ?",
                    vals,
                )

    db.commit()


def migrate_wyniki_to_rounds(db: sqlite3.Connection) -> int:
    """Migrate legacy sekcja names to round-suffixed format.
    przed_standaryzacja → analiza__1
    analiza_koncowa → analiza__2 (only for products that had przed_standaryzacja)
    Returns count of updated rows.
    """
    updated = 0

    # Find EBRs that have przed_standaryzacja results
    ebr_ids_with_przed = db.execute(
        "SELECT DISTINCT ebr_id FROM ebr_wyniki WHERE sekcja = 'przed_standaryzacja'"
    ).fetchall()
    ebr_ids_with_przed = {r[0] for r in ebr_ids_with_przed}

    if ebr_ids_with_przed:
        placeholders = ",".join(["?"] * len(ebr_ids_with_przed))
        # Rename przed_standaryzacja → analiza__1
        c = db.execute(
            f"UPDATE ebr_wyniki SET sekcja = 'analiza__1' WHERE sekcja = 'przed_standaryzacja' AND ebr_id IN ({placeholders})",
            list(ebr_ids_with_przed),
        )
        updated += c.rowcount

        # Rename analiza_koncowa → analiza__2 for same EBRs
        c = db.execute(
            f"UPDATE ebr_wyniki SET sekcja = 'analiza__2' WHERE sekcja = 'analiza_koncowa' AND ebr_id IN ({placeholders})",
            list(ebr_ids_with_przed),
        )
        updated += c.rowcount

    db.commit()
    return updated
