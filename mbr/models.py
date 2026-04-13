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
            rola            TEXT NOT NULL CHECK(rola IN ('technolog', 'lab', 'cert', 'admin')),
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
                                CHECK(typ IN ('szarza', 'zbiornik', 'platkowanie')),
            nastaw              INTEGER,
            przepompowanie_json TEXT,
            uwagi_koncowe       TEXT
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

        CREATE TABLE IF NOT EXISTS ebr_uwagi_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ebr_id     INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
            tekst      TEXT,
            action     TEXT NOT NULL CHECK(action IN ('create', 'update', 'delete')),
            autor      TEXT NOT NULL,
            dt         TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS produkty (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nazwa TEXT UNIQUE NOT NULL,
            kod TEXT,
            aktywny INTEGER DEFAULT 1,
            typy TEXT DEFAULT '["szarza"]',
            display_name TEXT,
            spec_number TEXT,
            cas_number TEXT,
            expiry_months INTEGER DEFAULT 12,
            opinion_pl TEXT,
            opinion_en TEXT
        );

        CREATE TABLE IF NOT EXISTS zbiorniki (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nr_zbiornika TEXT UNIQUE NOT NULL,
            max_pojemnosc REAL,
            produkt TEXT,
            kod_produktu TEXT,
            aktywny INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS zbiornik_szarze (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ebr_id INTEGER NOT NULL,
            zbiornik_id INTEGER NOT NULL REFERENCES zbiorniki(id),
            masa_kg REAL,
            dt_dodania TEXT,
            UNIQUE(ebr_id, zbiornik_id)
        );

        CREATE TABLE IF NOT EXISTS etapy_procesowe (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kod TEXT UNIQUE NOT NULL,
            label TEXT NOT NULL,
            aktywny INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS produkt_etapy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produkt TEXT NOT NULL,
            etap_kod TEXT NOT NULL,
            kolejnosc INTEGER DEFAULT 0,
            rownolegle INTEGER DEFAULT 0,
            UNIQUE(produkt, etap_kod)
        );

        CREATE TABLE IF NOT EXISTS substraty (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nazwa TEXT UNIQUE NOT NULL,
            aktywny INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS substrat_produkty (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            substrat_id INTEGER NOT NULL REFERENCES substraty(id),
            produkt TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS platkowanie_substraty (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ebr_id INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
            substrat_id INTEGER NOT NULL REFERENCES substraty(id),
            nr_partii_substratu TEXT
        );
    """)
    # Seed zbiorniki (tanks) — INSERT OR IGNORE for idempotency
    _ZBIORNIKI_SEED = [
        ("M1", 30, "Cheginy GLOL"), ("M2", 30, "Cheginy GLO"),
        ("M3", 35, "Cheginy GLOL"), ("M4", 20, "Alkohole Cetostearylowe"),
        ("M5", 27, "DEA"), ("M6", 25, "Chelamid DK"),
        ("M7", 12, "Olej palmowy"), ("M8", 25, "Olej palmowy"),
        ("M9", 22, "Cheginy"), ("M10", 33, "Chelamid"),
        ("M11", 30, "Kwasy kokosowe"), ("M12", 30, "DMAPA"),
        ("M13", 25, "Olej kokosowy"), ("M14", 48, "Cheginy KK"),
        ("M15", 42, "Cheginy K7"), ("M16", 25, "Cheginy GL"),
        ("M17", 25, "Cheginy GLO"), ("M18", 27, "Chelamid DK"),
        ("M19", 25, "Kwasy kokosowe"),
    ]
    for nr, cap, prod in _ZBIORNIKI_SEED:
        db.execute(
            "INSERT OR IGNORE INTO zbiorniki (nr_zbiornika, max_pojemnosc, produkt) VALUES (?, ?, ?)",
            (nr, cap, prod),
        )

    # Seed produkty with auto-derived codes
    _PRODUKTY_SEED = [
        # (nazwa, kod)
        ("Chegina_K40GL", "GL"), ("Chegina_K40GLO", "GLO"), ("Chegina_K40GLOL", "GLOL"),
        ("Chegina_K7", "K7"), ("Chegina_K40GLOS", "GLOS"), ("Chegina_K40GLOL_HQ", "GLOL_HQ"),
        ("Chegina_K7GLO", "K7GLO"), ("Chegina_K7B", "K7B"),
        ("Chegina_KK", "KK"), ("Chegina_CC", "CC"), ("Chegina_CCR", "CCR"),
        ("Chegina_L9", "L9"), ("Chegina", "CHEGINA"),
        ("Cheminox_K", "CHX_K"), ("Cheminox_K35", "CHX_K35"), ("Cheminox_LA", "CHX_LA"),
        ("Chemipol_ML", "CPL_ML"), ("Chemipol_OL", "CPL_OL"),
        ("Monamid_KO", "MKO"), ("Monamid_KO_Revada", "MKO_R"), ("Monamid_K", "MK"),
        ("Monamid_L", "ML"), ("Monamid_S", "MS"),
        ("Dister_E", "DIST_E"), ("Monester_O", "MON_O"), ("Monester_S", "MON_S"),
        ("Alkinol", "ALK"), ("Alkinol_B", "ALK_B"), ("Alstermid_K", "AST_K"), ("Alstermid", "AST"),
        ("Chemal_CS3070", "CML_CS"), ("Chemal_EO20", "CML_EO"), ("Chemal_SE12", "CML_SE"), ("Chemal_PC", "CML_PC"),
        ("Polcet_A", "POL_A"), ("Chelamid_DK", "DK"), ("Glikoster_P", "GLIK"),
        ("Citrowax", "CWAX"), ("Kwas_stearynowy", "KS"), ("Perlico_45", "PER45"),
        ("SLES", "SLES"), ("HSH_CS3070", "HSH_CS"),
    ]
    for nazwa, kod in _PRODUKTY_SEED:
        db.execute(
            "INSERT OR IGNORE INTO produkty (nazwa, kod) VALUES (?, ?)",
            (nazwa, kod),
        )

    # Migration: add kod_produktu column if missing (existing DBs)
    cols = [r[1] for r in db.execute("PRAGMA table_info(zbiorniki)").fetchall()]
    if "kod_produktu" not in cols:
        db.execute("ALTER TABLE zbiorniki ADD COLUMN kod_produktu TEXT")

    # Migration: add typy column to produkty if missing
    pr_cols = [r[1] for r in db.execute("PRAGMA table_info(produkty)").fetchall()]
    if "typy" not in pr_cols:
        db.execute("ALTER TABLE produkty ADD COLUMN typy TEXT DEFAULT '[\"szarza\"]'")

    # Set typy for Cheginy products (szarza + zbiornik + platkowanie)
    _CHEGINY_ALL_TYPY = '["szarza","zbiornik","platkowanie"]'
    for nazwa, _ in _PRODUKTY_SEED:
        if nazwa.startswith("Chegina_"):
            db.execute(
                "UPDATE produkty SET typy = ? WHERE nazwa = ? AND typy = '[\"szarza\"]'",
                (_CHEGINY_ALL_TYPY, nazwa),
            )

    # Migration: add certificate metadata columns to produkty
    for col, coldef in [
        ("display_name", "TEXT"),
        ("spec_number", "TEXT"),
        ("cas_number", "TEXT"),
        ("expiry_months", "INTEGER DEFAULT 12"),
        ("opinion_pl", "TEXT"),
        ("opinion_en", "TEXT"),
    ]:
        try:
            db.execute(f"ALTER TABLE produkty ADD COLUMN {col} {coldef}")
            db.commit()
        except Exception:
            pass

    # Auto-generate display_name from nazwa where missing
    db.execute("""
        UPDATE produkty SET display_name = REPLACE(nazwa, '_', ' ')
        WHERE display_name IS NULL OR display_name = ''
    """)
    db.commit()

    # Auto-sync: products in mbr_templates but not in produkty
    db.execute("""
        INSERT OR IGNORE INTO produkty (nazwa, display_name)
        SELECT DISTINCT produkt, REPLACE(produkt, '_', ' ')
        FROM mbr_templates
        WHERE produkt NOT IN (SELECT nazwa FROM produkty)
    """)
    db.commit()

    # Map zbiornik product names → codes
    _ZB_PRODUKT_TO_KOD = {
        "Cheginy GLOL": "GLOL", "Cheginy GLO": "GLO", "Cheginy GL": "GL",
        "Cheginy K7": "K7", "Cheginy KK": "KK", "Cheginy": "CHEGINA",
        "Chelamid DK": "DK", "Chelamid": "DK",
        "Alkohole Cetostearylowe": "ALK",
        "DEA": "DK", "Olej palmowy": None, "Olej kokosowy": None,
        "Kwasy kokosowe": None, "DMAPA": None,
    }
    for zb_prod, kod in _ZB_PRODUKT_TO_KOD.items():
        if kod:
            db.execute(
                "UPDATE zbiorniki SET kod_produktu = ? WHERE produkt = ? AND (kod_produktu IS NULL OR kod_produktu = '')",
                (kod, zb_prod),
            )

    db.commit()

    # Migration: add jednostka column to parametry_analityczne
    pa_cols = [r[1] for r in db.execute("PRAGMA table_info(parametry_analityczne)").fetchall()]
    if "jednostka" not in pa_cols:
        try:
            db.execute("ALTER TABLE parametry_analityczne ADD COLUMN jednostka TEXT")
        except Exception:
            pass  # table may not exist yet; will be created below

    # Migration: add target column to parametry_etapy
    pe_cols = [r[1] for r in db.execute("PRAGMA table_info(parametry_etapy)").fetchall()]
    if "target" not in pe_cols:
        try:
            db.execute("ALTER TABLE parametry_etapy ADD COLUMN target REAL")
        except Exception:
            pass  # table may not exist yet; will be created below

    # Migration: recreate parametry_analityczne without CHECK constraint on typ
    # (allows 'binarny' type; SQLite can't ALTER CHECK)
    # Use separate connection to avoid transaction issues
    # Skip on fresh DB where parametry_analityczne doesn't exist yet
    _pa_exists = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='parametry_analityczne'").fetchone()
    _needs_check_migration = False
    if _pa_exists:
        try:
            db.execute("INSERT INTO parametry_analityczne (kod,label,typ) VALUES ('__test_binarny','test','binarny')")
            db.execute("DELETE FROM parametry_analityczne WHERE kod='__test_binarny'")
        except Exception:
            _needs_check_migration = True
            db.rollback()

    if _needs_check_migration:
        import sqlite3 as _sq
        _mdb = _sq.connect(str(DB_PATH))
        _mdb.executescript("""
            DROP TABLE IF EXISTS parametry_analityczne_new;
            CREATE TABLE parametry_analityczne_new (
                id              INTEGER PRIMARY KEY,
                kod             TEXT NOT NULL UNIQUE,
                label           TEXT NOT NULL,
                typ             TEXT NOT NULL,
                metoda_nazwa    TEXT,
                metoda_formula  TEXT,
                metoda_factor   REAL,
                formula         TEXT,
                precision       INTEGER DEFAULT 2,
                aktywny         INTEGER DEFAULT 1,
                skrot           TEXT,
                metoda_id       INTEGER,
                jednostka       TEXT
            );
            INSERT INTO parametry_analityczne_new SELECT id, kod, label, typ, metoda_nazwa, metoda_formula, metoda_factor, formula, precision, aktywny, skrot, metoda_id, jednostka FROM parametry_analityczne;
            DROP TABLE parametry_analityczne;
            ALTER TABLE parametry_analityczne_new RENAME TO parametry_analityczne;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pa_kod ON parametry_analityczne(kod);
        """)
        _mdb.close()

    # Seed etapy_procesowe
    _ETAPY_SEED = [
        ("amidowanie", "Amidowanie"), ("namca", "NaMCA"),
        ("czwartorzedowanie", "Czwartorzędowanie"), ("sulfonowanie", "Sulfonowanie"),
        ("utlenienie", "Utlenienie"), ("rozjasnianie", "Rozjaśnianie"),
        ("standaryzacja", "Standaryzacja"), ("analiza_koncowa", "Analiza końcowa"),
        ("dodatki", "Dodatki standaryzacyjne"),
    ]
    for kod, label in _ETAPY_SEED:
        db.execute("INSERT OR IGNORE INTO etapy_procesowe (kod, label) VALUES (?, ?)", (kod, label))

    # Seed produkt_etapy (K7 pipeline)
    _K7_PRODUCTS = ["Chegina_K7", "Chegina_K40GL"]
    _K7_STAGES = [("amidowanie", 1, 1), ("namca", 2, 1), ("czwartorzedowanie", 3, 0),
                  ("sulfonowanie", 4, 0), ("utlenienie", 5, 0)]
    for prod in _K7_PRODUCTS:
        for etap, kolej, rown in _K7_STAGES:
            db.execute("INSERT OR IGNORE INTO produkt_etapy (produkt, etap_kod, kolejnosc, rownolegle) VALUES (?,?,?,?)",
                       (prod, etap, kolej, rown))

    # Seed produkt_etapy (GLOL pipeline — K7 + rozjasnianie)
    _GLOL_PRODUCTS = ["Chegina_K40GLO", "Chegina_K40GLOL", "Chegina_K40GLOS",
                      "Chegina_K40GLOL_HQ", "Chegina_K40GLN", "Chegina_GLOL40"]
    _GLOL_STAGES = _K7_STAGES + [("rozjasnianie", 6, 0)]
    for prod in _GLOL_PRODUCTS:
        for etap, kolej, rown in _GLOL_STAGES:
            db.execute("INSERT OR IGNORE INTO produkt_etapy (produkt, etap_kod, kolejnosc, rownolegle) VALUES (?,?,?,?)",
                       (prod, etap, kolej, rown))

    # Migration: rename smca → namca in existing data
    try:
        db.execute("UPDATE OR IGNORE parametry_etapy SET kontekst = 'namca' WHERE kontekst = 'smca'")
        db.execute("UPDATE OR IGNORE ebr_etapy_status SET etap = 'namca' WHERE etap = 'smca'")
        db.execute("UPDATE OR IGNORE ebr_etapy_analizy SET etap = 'namca' WHERE etap = 'smca'")
        db.execute("UPDATE OR IGNORE produkt_etapy SET etap_kod = 'namca' WHERE etap_kod = 'smca'")
    except Exception:
        pass  # tables may not exist yet on fresh DB; will be created below

    db.commit()

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
            typ             TEXT NOT NULL,
            metoda_nazwa    TEXT,
            metoda_formula  TEXT,
            metoda_factor   REAL,
            formula         TEXT,
            precision       INTEGER DEFAULT 2,
            aktywny         INTEGER DEFAULT 1,
            skrot           TEXT,
            metoda_id       INTEGER REFERENCES metody_miareczkowe(id),
            jednostka       TEXT,
            name_en         TEXT,
            method_code     TEXT
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
            target          REAL,
            krok            INTEGER,
            cert_requirement       TEXT,
            cert_format            TEXT,
            cert_qualitative_result TEXT,
            cert_kolejnosc         INTEGER,
            on_cert                INTEGER DEFAULT 0,
            cert_variant_id        INTEGER,
            precision              INTEGER,
            grupa                  TEXT DEFAULT 'lab',
            UNIQUE(produkt, kontekst, parametr_id)
        )
    """)
    # --- Pipeline builder tables (analytical stages) ---
    db.execute("""
        CREATE TABLE IF NOT EXISTS etapy_analityczne (
            id                  INTEGER PRIMARY KEY,
            kod                 TEXT NOT NULL UNIQUE,
            nazwa               TEXT NOT NULL,
            opis                TEXT,
            typ_cyklu           TEXT NOT NULL DEFAULT 'jednorazowy'
                                CHECK(typ_cyklu IN ('jednorazowy', 'cykliczny')),
            aktywny             INTEGER DEFAULT 1,
            kolejnosc_domyslna  INTEGER DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS etap_parametry (
            id              INTEGER PRIMARY KEY,
            etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
            parametr_id     INTEGER NOT NULL REFERENCES parametry_analityczne(id),
            kolejnosc       INTEGER DEFAULT 0,
            min_limit       REAL,
            max_limit       REAL,
            nawazka_g       REAL,
            precision       INTEGER,
            target          REAL,
            wymagany        INTEGER DEFAULT 0,
            grupa           TEXT DEFAULT 'lab',
            formula         TEXT,
            sa_bias         REAL,
            krok            INTEGER,
            UNIQUE(etap_id, parametr_id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS produkt_pipeline (
            id              INTEGER PRIMARY KEY,
            produkt         TEXT NOT NULL,
            etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
            kolejnosc       INTEGER NOT NULL,
            UNIQUE(produkt, etap_id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS produkt_etap_limity (
            id              INTEGER PRIMARY KEY,
            produkt         TEXT NOT NULL,
            etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
            parametr_id     INTEGER NOT NULL REFERENCES parametry_analityczne(id),
            min_limit       REAL,
            max_limit       REAL,
            nawazka_g       REAL,
            precision       INTEGER,
            target          REAL,
            UNIQUE(produkt, etap_id, parametr_id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS etap_warunki (
            id              INTEGER PRIMARY KEY,
            etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
            parametr_id     INTEGER NOT NULL REFERENCES parametry_analityczne(id),
            operator        TEXT NOT NULL CHECK(operator IN ('<', '<=', '>=', '>', 'between', '=')),
            wartosc         REAL,
            wartosc_max     REAL,
            opis_warunku    TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS etap_korekty_katalog (
            id              INTEGER PRIMARY KEY,
            etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
            substancja      TEXT NOT NULL,
            jednostka       TEXT DEFAULT 'kg',
            wykonawca       TEXT NOT NULL DEFAULT 'produkcja'
                            CHECK(wykonawca IN ('laborant', 'produkcja')),
            kolejnosc       INTEGER DEFAULT 0,
            formula_ilosc   TEXT,
            formula_zmienne TEXT,
            formula_opis    TEXT,
            jest_przejscie  INTEGER DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS ebr_etap_sesja (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ebr_id          INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
            etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
            runda           INTEGER NOT NULL DEFAULT 1,
            status          TEXT NOT NULL DEFAULT 'w_trakcie'
                            CHECK(status IN ('w_trakcie', 'ok', 'poza_limitem', 'oczekuje_korekty')),
            dt_start        TEXT,
            dt_end          TEXT,
            laborant        TEXT,
            decyzja         TEXT CHECK(decyzja IN ('przejscie', 'korekta', 'korekta_i_przejscie')),
            komentarz       TEXT,
            UNIQUE(ebr_id, etap_id, runda)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS ebr_pomiar (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sesja_id        INTEGER NOT NULL REFERENCES ebr_etap_sesja(id),
            parametr_id     INTEGER NOT NULL REFERENCES parametry_analityczne(id),
            wartosc         REAL,
            min_limit       REAL,
            max_limit       REAL,
            w_limicie       INTEGER,
            is_manual       INTEGER NOT NULL DEFAULT 1,
            dt_wpisu        TEXT NOT NULL,
            wpisal          TEXT NOT NULL,
            UNIQUE(sesja_id, parametr_id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS ebr_korekta_v2 (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sesja_id        INTEGER NOT NULL REFERENCES ebr_etap_sesja(id),
            korekta_typ_id  INTEGER NOT NULL REFERENCES etap_korekty_katalog(id),
            ilosc           REAL,
            zalecil         TEXT,
            wykonawca_info  TEXT,
            dt_zalecenia    TEXT,
            dt_wykonania    TEXT,
            status          TEXT NOT NULL DEFAULT 'zalecona'
                            CHECK(status IN ('zalecona', 'wykonana', 'anulowana'))
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            dt              TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            entity_type     TEXT,
            entity_id       INTEGER,
            entity_label    TEXT,
            diff_json       TEXT,
            payload_json    TEXT,
            context_json    TEXT,
            request_id      TEXT,
            ip              TEXT,
            user_agent      TEXT,
            result          TEXT NOT NULL DEFAULT 'ok'
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS audit_log_actors (
            audit_id        INTEGER NOT NULL REFERENCES audit_log(id) ON DELETE CASCADE,
            worker_id       INTEGER,
            actor_login     TEXT NOT NULL,
            actor_rola      TEXT NOT NULL,
            actor_name      TEXT,
            PRIMARY KEY (audit_id, actor_login)
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_dt ON audit_log(dt DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_event_type ON audit_log(event_type)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_request ON audit_log(request_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_audit_actors_worker ON audit_log_actors(worker_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wyniki_ebr_limicie ON ebr_wyniki(ebr_id, w_limicie, dt_wpisu)")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ebr_uwagi_history_ebr "
        "ON ebr_uwagi_history(ebr_id, dt DESC)"
    )
    db.commit()

    # Migration: add actor_name to audit_log_actors + backfill from workers
    try:
        db.execute("ALTER TABLE audit_log_actors ADD COLUMN actor_name TEXT")
        db.execute("""
            UPDATE audit_log_actors SET actor_name = (
                SELECT w.imie || ' ' || w.nazwisko FROM workers w
                WHERE w.id = audit_log_actors.worker_id
            ) WHERE worker_id IS NOT NULL AND actor_name IS NULL
        """)
        db.commit()
    except Exception:
        pass

    # Migration: add typ column if missing (SQLite doesn't support ALTER TABLE ADD with CHECK)
    try:
        db.execute("ALTER TABLE ebr_batches ADD COLUMN typ TEXT NOT NULL DEFAULT 'szarza'")
        db.commit()
    except Exception:
        pass  # column already exists

    # Migration: rebuild ebr_batches CHECK constraint to allow 'platkowanie' typ
    try:
        row = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='ebr_batches'"
        ).fetchone()
        if row and "platkowanie" not in (row["sql"] or ""):
            db.execute("ALTER TABLE ebr_batches RENAME TO _ebr_batches_old")
            db.execute("""
                CREATE TABLE ebr_batches (
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
                                        CHECK(typ IN ('szarza', 'zbiornik', 'platkowanie')),
                    nastaw              INTEGER,
                    przepompowanie_json TEXT,
                    nr_zbiornika        TEXT DEFAULT ''
                )
            """)
            db.execute("INSERT INTO ebr_batches SELECT * FROM _ebr_batches_old")
            db.execute("DROP TABLE _ebr_batches_old")
            db.commit()
    except Exception:
        pass

    # Migration: fix ebr_wyniki FK reference (may point to _ebr_batches_old after ebr_batches rebuild)
    try:
        wy_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='ebr_wyniki'"
        ).fetchone()
        if wy_sql and "_ebr_batches_old" in (wy_sql["sql"] or ""):
            db.execute("ALTER TABLE ebr_wyniki RENAME TO _ebr_wyniki_old")
            db.execute("""
                CREATE TABLE ebr_wyniki (
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
                    samples_json    TEXT,
                    wartosc_text    TEXT,
                    UNIQUE(ebr_id, sekcja, kod_parametru)
                )
            """)
            db.execute("INSERT INTO ebr_wyniki SELECT * FROM _ebr_wyniki_old")
            db.execute("DROP TABLE _ebr_wyniki_old")
            db.commit()
    except Exception:
        pass

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

    # Migration: add cert columns to parametry_etapy (Phase 1 param centralization)
    for col, typedef in [
        ("cert_requirement", "TEXT"),
        ("cert_format", "TEXT"),
        ("cert_qualitative_result", "TEXT"),
        ("cert_kolejnosc", "INTEGER"),
        ("on_cert", "INTEGER DEFAULT 0"),
        ("cert_variant_id", "INTEGER"),
    ]:
        try:
            db.execute(f"ALTER TABLE parametry_etapy ADD COLUMN {col} {typedef}")
            db.commit()
        except Exception:
            pass

    # Migration: add precision to parametry_etapy (per-product precision override)
    try:
        db.execute("ALTER TABLE parametry_etapy ADD COLUMN precision INTEGER")
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

    # Migration: add uwagi_koncowe column for final batch notes
    try:
        db.execute("ALTER TABLE ebr_batches ADD COLUMN uwagi_koncowe TEXT")
        db.commit()
    except Exception:
        pass  # already exists

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
            if "'lab'" not in ddl:
                db.executescript("""
                    CREATE TABLE mbr_users_new (
                        user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        login           TEXT UNIQUE NOT NULL,
                        password_hash   TEXT NOT NULL,
                        rola            TEXT NOT NULL CHECK(rola IN ('technolog', 'lab', 'cert', 'admin')),
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

    # Migration: deduplicate parameter codes
    # woda → h2o, dea → dietanolamina, siarczynow → so3
    _PARAM_RENAMES = [
        ("woda", "h2o"),
        ("barwa_fau", "barwa_I2"),
        ("dea", "dietanolamina"),
        ("siarczynow", "so3"),
    ]
    for old_kod, new_kod in _PARAM_RENAMES:
        db.execute(
            "UPDATE ebr_wyniki SET kod_parametru = ? WHERE kod_parametru = ?",
            (new_kod, old_kod),
        )
        db.execute(
            "UPDATE OR IGNORE ebr_etapy_analizy SET kod_parametru = ? WHERE kod_parametru = ?",
            (new_kod, old_kod),
        )
        target_exists = db.execute(
            "SELECT id FROM parametry_analityczne WHERE kod = ?", (new_kod,)
        ).fetchone()
        if target_exists:
            old_param = db.execute(
                "SELECT id FROM parametry_analityczne WHERE kod = ?", (old_kod,)
            ).fetchone()
            if old_param:
                db.execute(
                    "UPDATE OR IGNORE parametry_etapy SET parametr_id = ? WHERE parametr_id = ?",
                    (target_exists[0], old_param[0]),
                )
                db.execute(
                    "DELETE FROM parametry_etapy WHERE parametr_id = ?",
                    (old_param[0],),
                )
                db.execute(
                    "DELETE FROM parametry_analityczne WHERE id = ?",
                    (old_param[0],),
                )
    db.commit()

    # Migration: add name_en to parametry_analityczne (English name for certificates)
    try:
        db.execute("ALTER TABLE parametry_analityczne ADD COLUMN name_en TEXT")
        db.commit()
    except Exception:
        pass

    # Migration: add method_code to parametry_analityczne (lab method code e.g. L928)
    try:
        db.execute("ALTER TABLE parametry_analityczne ADD COLUMN method_code TEXT")
        db.commit()
    except Exception:
        pass

    # Migration: create parametry_cert table (certificate parameter bindings)
    db.execute("""
        CREATE TABLE IF NOT EXISTS parametry_cert (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            produkt             TEXT NOT NULL,
            parametr_id         INTEGER NOT NULL REFERENCES parametry_analityczne(id),
            kolejnosc           INTEGER DEFAULT 0,
            requirement         TEXT,
            format              TEXT DEFAULT '1',
            qualitative_result  TEXT,
            UNIQUE(produkt, parametr_id)
        )
    """)
    db.commit()

    # Migration: create cert_variants table
    db.execute("""
        CREATE TABLE IF NOT EXISTS cert_variants (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            produkt       TEXT NOT NULL,
            variant_id    TEXT NOT NULL,
            label         TEXT NOT NULL,
            flags         TEXT DEFAULT '[]',
            spec_number   TEXT,
            opinion_pl    TEXT,
            opinion_en    TEXT,
            avon_code     TEXT,
            avon_name     TEXT,
            remove_params TEXT DEFAULT '[]',
            kolejnosc     INTEGER DEFAULT 0,
            UNIQUE(produkt, variant_id)
        )
    """)
    db.commit()

    # Migration: add variant_id to parametry_cert (NULL = base product param, NOT NULL = add_parameter for variant)
    try:
        db.execute("ALTER TABLE parametry_cert ADD COLUMN variant_id INTEGER REFERENCES cert_variants(id)")
        db.commit()
    except Exception:
        pass

    # Migration: add name override columns to parametry_cert
    for col in ("name_pl", "name_en", "method"):
        try:
            db.execute(f"ALTER TABLE parametry_cert ADD COLUMN {col} TEXT")
            db.commit()
        except Exception:
            pass

    # Migration: fix swiadectwa FK reference (may point to _ebr_batches_old after ebr_batches rebuild)
    try:
        sw_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='swiadectwa'"
        ).fetchone()
        if sw_sql and "_ebr_batches_old" in (sw_sql["sql"] or ""):
            db.execute("ALTER TABLE swiadectwa RENAME TO _swiadectwa_old")
            db.execute("""
                CREATE TABLE swiadectwa (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    ebr_id          INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
                    template_name   TEXT NOT NULL,
                    nr_partii       TEXT NOT NULL,
                    pdf_path        TEXT NOT NULL,
                    dt_wystawienia  TEXT NOT NULL,
                    wystawil        TEXT NOT NULL,
                    nieaktualne     INTEGER DEFAULT 0,
                    data_json       TEXT
                )
            """)
            db.execute("INSERT INTO swiadectwa SELECT * FROM _swiadectwa_old")
            db.execute("DROP TABLE _swiadectwa_old")
            db.commit()
    except Exception:
        pass

    # Migration: fix platkowanie_substraty FK reference (may point to _ebr_batches_old after ebr_batches rebuild)
    try:
        ps_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='platkowanie_substraty'"
        ).fetchone()
        if ps_sql and "_ebr_batches_old" in (ps_sql["sql"] or ""):
            db.execute("ALTER TABLE platkowanie_substraty RENAME TO _platkowanie_substraty_old")
            db.execute("""
                CREATE TABLE platkowanie_substraty (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ebr_id INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
                    substrat_id INTEGER NOT NULL REFERENCES substraty(id),
                    nr_partii_substratu TEXT
                )
            """)
            db.execute("INSERT INTO platkowanie_substraty SELECT * FROM _platkowanie_substraty_old")
            db.execute("DROP TABLE _platkowanie_substraty_old")
            db.commit()
    except Exception:
        pass

    # Migration: product_ref_values — per-product reference values for analiza_koncowa
    db.execute("""
        CREATE TABLE IF NOT EXISTS product_ref_values (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            produkt       TEXT NOT NULL,
            kontekst      TEXT NOT NULL DEFAULT 'analiza_koncowa',
            parametr_kod  TEXT NOT NULL,
            wartosc       REAL,
            wartosc_text  TEXT,
            UNIQUE(produkt, kontekst, parametr_kod)
        )
    """)
    db.commit()

    # Migration: add korekta_i_przejscie to ebr_etap_sesja.decyzja CHECK
    try:
        db.execute("INSERT INTO ebr_etap_sesja (ebr_id,etap_id,runda,decyzja) VALUES (0,0,0,'korekta_i_przejscie')")
        db.execute("DELETE FROM ebr_etap_sesja WHERE ebr_id=0 AND etap_id=0 AND runda=0")
        db.commit()
    except Exception:
        # CHECK already allows it (fresh DB) or needs recreate
        try:
            db.rollback()
            db.executescript("""
                ALTER TABLE ebr_etap_sesja RENAME TO _ebr_etap_sesja_old;
                CREATE TABLE ebr_etap_sesja (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    ebr_id   INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
                    etap_id  INTEGER NOT NULL REFERENCES etapy_analityczne(id),
                    runda    INTEGER NOT NULL DEFAULT 1,
                    status   TEXT NOT NULL DEFAULT 'w_trakcie'
                             CHECK(status IN ('w_trakcie','ok','poza_limitem','oczekuje_korekty')),
                    dt_start TEXT, dt_end TEXT, laborant TEXT,
                    decyzja  TEXT CHECK(decyzja IN ('przejscie','korekta','korekta_i_przejscie')),
                    komentarz TEXT,
                    UNIQUE(ebr_id, etap_id, runda)
                );
                INSERT INTO ebr_etap_sesja SELECT * FROM _ebr_etap_sesja_old;
                DROP TABLE _ebr_etap_sesja_old;
            """)
        except Exception:
            pass

    # Migration: rename h2o2 skrót → %Perh., add nadtlenki parameter,
    # replace h2o2 with nadtlenki in analiza_koncowa for betaine products
    try:
        # 1. Rename h2o2 skrót (idempotent — UPDATE only when still old value)
        db.execute(
            "UPDATE parametry_analityczne SET skrot='%Perh.' "
            "WHERE kod='h2o2' AND (skrot IS NULL OR skrot != '%Perh.')"
        )

        # 2. Ensure "Nadtlenki [%]" method exists in metody_miareczkowe
        #    (seed_metody may not have run yet — e.g. in tests)
        import json as _json
        db.execute("""
            INSERT OR IGNORE INTO metody_miareczkowe
                (nazwa, formula, mass_required, volumes_json, titrants_json)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "Nadtlenki [%]",
            "(V1 * T1 * 1.704) / M",
            1,
            _json.dumps([{"label": "VCe [ml]", "titrant": "T1"}]),
            _json.dumps([{"id": "T1", "label": "C(Ce)", "default": 0.1}]),
        ))

        # 3. Look up metoda_id by name (resilient to ID shifts)
        _metoda = db.execute(
            "SELECT id FROM metody_miareczkowe WHERE nazwa='Nadtlenki [%]'"
        ).fetchone()
        _metoda_id = _metoda["id"] if _metoda else None

        # 4. Insert nadtlenki parameter (INSERT OR IGNORE = idempotent)
        db.execute("""
            INSERT OR IGNORE INTO parametry_analityczne
                (kod, label, typ, skrot, metoda_id, jednostka)
            VALUES
                ('nadtlenki', 'Nadtlenki', 'titracja', '%H\u2082O\u2082', ?, '%')
        """, (_metoda_id,))

        # 4b. Populate legacy inline metoda columns (needed by get_parametry_for_kontekst)
        #     Idempotent: only updates when still NULL
        db.execute("""
            UPDATE parametry_analityczne
            SET metoda_nazwa='Nadtlenki [%]',
                metoda_formula='(V1 * T1 * 1.704) / M',
                metoda_factor=1.704
            WHERE kod='nadtlenki' AND metoda_factor IS NULL
        """)

        # 5. Replace h2o2 → nadtlenki in parametry_etapy for analiza_koncowa
        _NADTLENKI_PRODUCTS = [
            # (produkt, kolejnosc, min_limit, max_limit, nawazka_g)
            ("Chegina_K40GLOL", 7,  0.0, 0.01, 10.0),
            ("Cheminox_K",      3,  0.0, 0.01, None),
            ("Cheminox_K35",    3,  0.0, 0.01, None),
            ("Cheminox_LA",     3,  0.0, 0.01, None),
            ("Chemipol_ML",     4,  0.0, 0.15, None),
        ]
        import sys as _sys
        _h2o2_row = db.execute(
            "SELECT id FROM parametry_analityczne WHERE kod='h2o2'"
        ).fetchone()
        _nadtlenki_row = db.execute(
            "SELECT id FROM parametry_analityczne WHERE kod='nadtlenki'"
        ).fetchone()

        if not (_h2o2_row and _nadtlenki_row):
            print("[migration] nadtlenki: skipping swap — h2o2 or nadtlenki param not found", file=_sys.stderr)
        else:
            _h2o2_id = _h2o2_row["id"]
            _nadtlenki_id = _nadtlenki_row["id"]

            for _prod, _kol, _mn, _mx, _naw in _NADTLENKI_PRODUCTS:
                # Remove old h2o2 binding for this product/context
                db.execute(
                    "DELETE FROM parametry_etapy "
                    "WHERE produkt=? AND kontekst='analiza_koncowa' AND parametr_id=?",
                    (_prod, _h2o2_id),
                )
                # Insert nadtlenki binding (INSERT OR IGNORE = idempotent)
                db.execute("""
                    INSERT OR IGNORE INTO parametry_etapy
                        (produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit, nawazka_g, wymagany)
                    VALUES (?, 'analiza_koncowa', ?, ?, ?, ?, ?, 1)
                """, (_prod, _nadtlenki_id, _kol, _mn, _mx, _naw))

            # 6. Rebuild parametry_lab in active MBR templates so forms show nadtlenki
            try:
                from mbr.parametry.registry import build_parametry_lab as _bpl
                import json as _plab_json
                for _prod, _, _, _, _ in _NADTLENKI_PRODUCTS:
                    _plab = _bpl(db, _prod)
                    db.execute(
                        "UPDATE mbr_templates SET parametry_lab=? "
                        "WHERE produkt=? AND status='active'",
                        (_plab_json.dumps(_plab, ensure_ascii=False), _prod),
                    )
            except Exception as _pe:
                print(f"[migration] nadtlenki: parametry_lab rebuild failed: {_pe}", file=_sys.stderr)

        db.commit()
    except Exception as _e:
        import sys as _sys
        print(f"[migration] nadtlenki: {_e}", file=_sys.stderr)

    # Migration: add grupa to parametry_etapy (parameter ownership: lab/kj/rnd)
    try:
        db.execute("ALTER TABLE parametry_etapy ADD COLUMN grupa TEXT DEFAULT 'lab'")
        db.commit()
    except Exception:
        pass

    # Migration: add default_grupa to mbr_users (default parameter group filter)
    try:
        db.execute("ALTER TABLE mbr_users ADD COLUMN default_grupa TEXT DEFAULT 'lab'")
        db.commit()
    except Exception:
        pass

    # Migration: add jest_przejscie to etap_korekty_katalog
    try:
        ek_cols = [r[1] for r in db.execute("PRAGMA table_info(etap_korekty_katalog)").fetchall()]
        if "jest_przejscie" not in ek_cols:
            db.execute("ALTER TABLE etap_korekty_katalog ADD COLUMN jest_przejscie INTEGER DEFAULT 0")
            db.commit()
    except Exception:
        pass

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
