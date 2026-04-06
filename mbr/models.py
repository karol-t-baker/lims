"""
models.py — Database helpers and user CRUD for MBR/EBR webapp.
"""

import sqlite3
from pathlib import Path

from mbr.db import get_db, db_session  # noqa: F401

DB_PATH = Path(__file__).parent.parent / "data" / "batch_db_v4.sqlite"

from mbr.laborant.models import PRODUCTS  # noqa: F401


def init_mbr_tables(db: sqlite3.Connection) -> None:
    """Create MBR/EBR tables if they don't exist."""
    db.executescript("""
        CREATE TABLE IF NOT EXISTS mbr_users (
            user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            login           TEXT UNIQUE NOT NULL,
            password_hash   TEXT NOT NULL,
            rola            TEXT NOT NULL CHECK(rola IN ('technolog', 'laborant', 'laborant_kj', 'laborant_coa', 'admin')),
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
                                CHECK(typ IN ('szarza', 'zbiornik')),
            nastaw              INTEGER,
            przepompowanie_json TEXT
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

        CREATE TABLE IF NOT EXISTS ebr_etapy_analizy (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ebr_id          INTEGER NOT NULL,
            etap            TEXT NOT NULL,
            runda           INTEGER DEFAULT 1,
            kod_parametru   TEXT NOT NULL,
            wartosc         REAL,
            dt_wpisu        TEXT,
            wpisal          TEXT,
            UNIQUE(ebr_id, etap, runda, kod_parametru)
        );

        CREATE TABLE IF NOT EXISTS ebr_korekty (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ebr_id          INTEGER NOT NULL,
            etap            TEXT NOT NULL,
            po_rundzie      INTEGER,
            substancja      TEXT NOT NULL,
            ilosc_kg        REAL,
            zalecil         TEXT,
            wykonano        INTEGER DEFAULT 0,
            dt_zalecenia    TEXT,
            dt_wykonania    TEXT
        );

        CREATE TABLE IF NOT EXISTS ebr_etapy_status (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ebr_id          INTEGER NOT NULL,
            etap            TEXT NOT NULL,
            status          TEXT DEFAULT 'pending',
            dt_start        TEXT,
            dt_end          TEXT,
            zatwierdzil     TEXT,
            UNIQUE(ebr_id, etap)
        );
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            imie        TEXT NOT NULL,
            nazwisko    TEXT NOT NULL,
            inicjaly    TEXT NOT NULL,
            nickname    TEXT DEFAULT '',
            avatar_icon INTEGER DEFAULT 0,
            avatar_color INTEGER DEFAULT 0,
            aktywny     INTEGER NOT NULL DEFAULT 1
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            text    TEXT NOT NULL,
            who     TEXT NOT NULL,
            dt      TEXT NOT NULL,
            priorytet TEXT DEFAULT 'normal'
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS swiadectwa (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ebr_id          INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
            template_name   TEXT NOT NULL,
            nr_partii       TEXT NOT NULL,
            pdf_path        TEXT NOT NULL,
            dt_wystawienia  TEXT NOT NULL,
            wystawil        TEXT NOT NULL,
            nieaktualne     INTEGER DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            login   TEXT NOT NULL,
            key     TEXT NOT NULL,
            value   TEXT,
            UNIQUE(login, key)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS metody_miareczkowe (
            id              INTEGER PRIMARY KEY,
            nazwa           TEXT NOT NULL UNIQUE,
            formula         TEXT NOT NULL,
            mass_required   INTEGER DEFAULT 1,
            volumes_json    TEXT NOT NULL DEFAULT '[]',
            titrants_json   TEXT NOT NULL DEFAULT '[]',
            aktywna         INTEGER DEFAULT 1
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS parametry_analityczne (
            id              INTEGER PRIMARY KEY,
            kod             TEXT NOT NULL UNIQUE,
            label           TEXT NOT NULL,
            typ             TEXT NOT NULL CHECK(typ IN ('bezposredni', 'titracja', 'obliczeniowy')),
            metoda_nazwa    TEXT,
            metoda_formula  TEXT,
            metoda_factor   REAL,
            formula         TEXT,
            precision       INTEGER DEFAULT 2,
            aktywny         INTEGER DEFAULT 1
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS parametry_etapy (
            id              INTEGER PRIMARY KEY,
            produkt         TEXT,
            kontekst        TEXT NOT NULL,
            parametr_id     INTEGER NOT NULL REFERENCES parametry_analityczne(id),
            kolejnosc       INTEGER DEFAULT 0,
            min_limit       REAL,
            max_limit       REAL,
            nawazka_g       REAL,
            wymagany        INTEGER DEFAULT 0,
            UNIQUE(produkt, kontekst, parametr_id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            dt          TEXT NOT NULL,
            tabela      TEXT NOT NULL,
            rekord_id   INTEGER NOT NULL,
            pole        TEXT NOT NULL,
            stara_wartosc TEXT,
            nowa_wartosc  TEXT,
            zmienil     TEXT NOT NULL
        )
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

    # Migration: add skrot column to parametry_analityczne
    try:
        db.execute("ALTER TABLE parametry_analityczne ADD COLUMN skrot TEXT")
        db.commit()
    except Exception:
        pass

    # Migration: add nastaw + przepompowanie columns if not exists
    cols = [r[1] for r in db.execute("PRAGMA table_info(ebr_batches)").fetchall()]
    if "nastaw" not in cols:
        db.execute("ALTER TABLE ebr_batches ADD COLUMN nastaw INTEGER")
    if "przepompowanie_json" not in cols:
        db.execute("ALTER TABLE ebr_batches ADD COLUMN przepompowanie_json TEXT")
    if "nr_zbiornika" not in cols:
        db.execute("ALTER TABLE ebr_batches ADD COLUMN nr_zbiornika TEXT")
    db.commit()

    # Migration: add avatar columns to workers if not exists
    wcols = [r[1] for r in db.execute("PRAGMA table_info(workers)").fetchall()]
    if "avatar_icon" not in wcols:
        db.execute("ALTER TABLE workers ADD COLUMN avatar_icon INTEGER DEFAULT 0")
        db.execute("ALTER TABLE workers ADD COLUMN avatar_color INTEGER DEFAULT 0")
        db.commit()

    # Migration: add nieaktualne column to swiadectwa if not exists
    try:
        db.execute("ALTER TABLE swiadectwa ADD COLUMN nieaktualne INTEGER DEFAULT 0")
        db.commit()
    except Exception:
        pass

    # Migration: add data_json column to swiadectwa (generation inputs for regeneration)
    try:
        db.execute("ALTER TABLE swiadectwa ADD COLUMN data_json TEXT")
        db.commit()
    except Exception:
        pass

    # Migration: add formula override to parametry_etapy (per-product formula)
    try:
        db.execute("ALTER TABLE parametry_etapy ADD COLUMN formula TEXT")
        db.commit()
    except Exception:
        pass

    # Migration: add sa_bias to parametry_etapy
    try:
        db.execute("ALTER TABLE parametry_etapy ADD COLUMN sa_bias REAL")
        db.commit()
    except Exception:
        pass

    # Migration: add stezenia_json to metody_miareczkowe (persistent titrant concentrations)
    try:
        db.execute("ALTER TABLE metody_miareczkowe ADD COLUMN stezenia_json TEXT")
        db.commit()
    except Exception:
        pass

    # Migration: add metoda_id to parametry_analityczne
    try:
        db.execute("ALTER TABLE parametry_analityczne ADD COLUMN metoda_id INTEGER REFERENCES metody_miareczkowe(id)")
        db.commit()
    except Exception:
        pass

    # Migration: golden batch flag
    try:
        db.execute("ALTER TABLE ebr_batches ADD COLUMN is_golden INTEGER DEFAULT 0")
        db.commit()
    except Exception:
        pass

    # Migration: wartosc_text for hybrid fields (mętność: number or text like "mętna jasna")
    try:
        db.execute("ALTER TABLE ebr_etapy_analizy ADD COLUMN wartosc_text TEXT")
        db.commit()
    except Exception:
        pass
    try:
        db.execute("ALTER TABLE ebr_wyniki ADD COLUMN wartosc_text TEXT")
        db.commit()
    except Exception:
        pass

    # Migration: add krok to ebr_etapy_analizy (sub-steps within stages)
    try:
        db.execute("ALTER TABLE ebr_etapy_analizy ADD COLUMN krok INTEGER DEFAULT 1")
        db.commit()
    except Exception:
        pass

    # Migration: add krok to parametry_etapy (which params appear at which sub-step)
    try:
        db.execute("ALTER TABLE parametry_etapy ADD COLUMN krok INTEGER")
        db.commit()
    except Exception:
        pass

    # Migration: add priorytet column to feedback
    try:
        db.execute("ALTER TABLE feedback ADD COLUMN priorytet TEXT DEFAULT 'normal'")
        db.commit()
    except Exception:
        pass

    # Migration: expand rola CHECK to include all roles
    # SQLite can't ALTER CHECK constraints, so recreate table if needed
    try:
        row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='mbr_users'").fetchone()
        if row:
            ddl = row[0] if isinstance(row, tuple) else row["sql"]
            if "'laborant_kj'" not in ddl:
                db.executescript("""
                    CREATE TABLE mbr_users_new (
                        user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        login           TEXT UNIQUE NOT NULL,
                        password_hash   TEXT NOT NULL,
                        rola            TEXT NOT NULL CHECK(rola IN ('technolog', 'laborant', 'laborant_kj', 'laborant_coa', 'admin')),
                        imie_nazwisko   TEXT
                    );
                    INSERT INTO mbr_users_new SELECT * FROM mbr_users;
                    DROP TABLE mbr_users;
                    ALTER TABLE mbr_users_new RENAME TO mbr_users;
                """)
    except Exception:
        pass

    # Migration: add sync_seq to ebr_batches for index-based COA sync
    try:
        db.execute("ALTER TABLE ebr_batches ADD COLUMN sync_seq INTEGER")
        db.commit()
    except Exception:
        pass  # column already exists

    db.execute("CREATE INDEX IF NOT EXISTS idx_batches_sync_seq ON ebr_batches(sync_seq)")

    # Backfill sync_seq for already-completed batches (ordered by dt_end)
    db.execute("""
        UPDATE ebr_batches SET sync_seq = (
            SELECT COUNT(*) FROM ebr_batches b2
            WHERE b2.status = 'completed'
              AND (b2.dt_end < ebr_batches.dt_end
                   OR (b2.dt_end = ebr_batches.dt_end AND b2.ebr_id <= ebr_batches.ebr_id))
        )
        WHERE status = 'completed' AND sync_seq IS NULL
    """)
    db.commit()


# ---------------------------------------------------------------------------
# Auto-numbering — moved to mbr.laborant.models, re-exported for backward compat
# ---------------------------------------------------------------------------

from mbr.laborant.models import next_nr_partii  # noqa: F401


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

from mbr.auth.models import create_user, verify_user  # noqa: F401


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

from mbr.workers.models import list_workers, update_worker_profile, update_worker_nickname  # noqa: F401


# ---------------------------------------------------------------------------
# MBR CRUD — moved to mbr.technolog.models, re-exported for backward compat
# ---------------------------------------------------------------------------

from mbr.technolog.models import list_mbr, get_mbr, get_active_mbr, save_mbr, activate_mbr, clone_mbr  # noqa: F401, E402


# ---------------------------------------------------------------------------
# EBR Dashboard queries — moved to mbr.laborant.models, re-exported for backward compat
# ---------------------------------------------------------------------------

from mbr.laborant.models import (  # noqa: F401, E402
    list_ebr_open,
    _compute_stage_info,
    list_ebr_completed,
    list_ebr_recent,
)


# Re-exports for backward compatibility — implementations moved to mbr.registry.models
from mbr.registry.models import (  # noqa: E402, F401
    list_completed_registry,
    get_registry_columns,
    list_completed_products,
    export_wyniki_csv,
)


# ---------------------------------------------------------------------------
# EBR CRUD — moved to mbr.laborant.models, re-exported for backward compat
# ---------------------------------------------------------------------------

from mbr.laborant.models import (  # noqa: F401, E402
    create_ebr,
    get_ebr,
    get_ebr_wyniki,
    get_round_state,
    save_wyniki,
    complete_ebr,
    sync_ebr_to_v4,
    migrate_wyniki_to_rounds,
)


# ---------------------------------------------------------------------------
# Certificates (Świadectwa)
# ---------------------------------------------------------------------------

from mbr.certs.models import create_swiadectwo, list_swiadectwa, mark_swiadectwa_outdated  # noqa: F401
