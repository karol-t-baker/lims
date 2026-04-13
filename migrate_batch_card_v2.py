"""Migration: batch card V2 — etap_decyzje table, gate seeds, schema extensions.

Creates:
  - etap_decyzje table (decision catalog per stage)
Extends:
  - ebr_pomiar: +odziedziczony
  - ebr_etap_sesja: +komentarz_decyzji, relaxed decyzja CHECK
  - parametry_etapy: +edytowalny, +dt_modified, +modified_by
Seeds:
  - etap_decyzje for 4 products × 3 stages
  - etap_warunki for SO₃²⁻ and H₂O₂ gates

Idempotent — safe to run multiple times.

Usage:
    python migrate_batch_card_v2.py
"""

import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "batch_db.sqlite"


def main():
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found", file=sys.stderr)
        sys.exit(1)

    # ── 1. Backup ──────────────────────────────────────────────
    backup = DB_PATH.parent / f"{DB_PATH.name}.bak-pre-batch-card-v2"
    if not backup.exists():
        shutil.copy2(DB_PATH, backup)
        print(f"Backup → {backup}")
    else:
        print(f"Backup already exists: {backup}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # ── 2. CREATE etap_decyzje ─────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS etap_decyzje (
            id                  INTEGER PRIMARY KEY,
            etap_id             INTEGER NOT NULL REFERENCES etapy_analityczne(id),
            produkt             TEXT,
            typ                 TEXT NOT NULL CHECK (typ IN ('pass', 'fail')),
            kod                 TEXT NOT NULL,
            label               TEXT NOT NULL,
            akcja               TEXT NOT NULL CHECK (akcja IN ('next_stage', 'new_round', 'release', 'close', 'skip_to_next')),
            wymaga_komentarza   INTEGER DEFAULT 0,
            kolejnosc           INTEGER DEFAULT 0,
            aktywny             INTEGER DEFAULT 1
        )
    """)
    print("etap_decyzje table OK")

    # ── 3. ALTER ebr_pomiar — add odziedziczony ───────────────
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(ebr_pomiar)").fetchall()]
    if "odziedziczony" not in cols:
        conn.execute("ALTER TABLE ebr_pomiar ADD COLUMN odziedziczony INTEGER DEFAULT 0")
        print("Added ebr_pomiar.odziedziczony")
    else:
        print("ebr_pomiar.odziedziczony already exists")

    # ── 4. ALTER ebr_etap_sesja — add komentarz_decyzji ──────
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(ebr_etap_sesja)").fetchall()]
    if "komentarz_decyzji" not in cols:
        conn.execute("ALTER TABLE ebr_etap_sesja ADD COLUMN komentarz_decyzji TEXT")
        print("Added ebr_etap_sesja.komentarz_decyzji")
    else:
        print("ebr_etap_sesja.komentarz_decyzji already exists")

    # ── 5. ALTER parametry_etapy — add edytowalny, dt_modified, modified_by
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(parametry_etapy)").fetchall()]
    for col, typedef in [
        ("edytowalny", "INTEGER DEFAULT 1"),
        ("dt_modified", "TEXT"),
        ("modified_by", "INTEGER"),
    ]:
        if col not in cols:
            conn.execute(f"ALTER TABLE parametry_etapy ADD COLUMN {col} {typedef}")
            print(f"Added parametry_etapy.{col}")
        else:
            print(f"parametry_etapy.{col} already exists")

    # ── 6. Rebuild ebr_etap_sesja to extend decyzja CHECK ─────
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='ebr_etap_sesja'"
    ).fetchone()
    old_sql = row[0] or "" if row else ""

    new_decyzja_values = (
        "'zamknij_etap','reopen_etap',"
        "'przejscie','new_round','release_comment','close_note','skip_to_next'"
    )
    needs_rebuild = "przejscie" not in old_sql or "new_round" not in old_sql

    if needs_rebuild:
        print("Rebuilding ebr_etap_sesja (extended decyzja CHECK)…")
        # Must disable FK checks during table rebuild — renaming a table
        # referenced by FK-dependent tables would otherwise fail.
        conn.executescript(f"""
            PRAGMA foreign_keys = OFF;
            ALTER TABLE ebr_etap_sesja RENAME TO _ebr_etap_sesja_v2_old;
            CREATE TABLE ebr_etap_sesja (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ebr_id          INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
                etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
                runda           INTEGER NOT NULL DEFAULT 1,
                status          TEXT NOT NULL DEFAULT 'nierozpoczety'
                                CHECK(status IN ('nierozpoczety','w_trakcie','zamkniety')),
                dt_start        TEXT,
                dt_end          TEXT,
                laborant        TEXT,
                decyzja         TEXT CHECK(decyzja IN ({new_decyzja_values})),
                komentarz       TEXT,
                komentarz_decyzji TEXT,
                UNIQUE(ebr_id, etap_id, runda)
            );
            INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status,
                dt_start, dt_end, laborant, decyzja, komentarz, komentarz_decyzji)
                SELECT id, ebr_id, etap_id, runda, status,
                       dt_start, dt_end, laborant, decyzja, komentarz, komentarz_decyzji
                FROM _ebr_etap_sesja_v2_old;
            DROP TABLE _ebr_etap_sesja_v2_old;
        """)

        # Rebuild FK-dependent tables
        for tbl, ddl in [
            ("ebr_korekta_zlecenie", """CREATE TABLE ebr_korekta_zlecenie (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sesja_id INTEGER NOT NULL REFERENCES ebr_etap_sesja(id),
                zalecil TEXT NOT NULL,
                dt_zalecenia TEXT NOT NULL DEFAULT (datetime('now')),
                dt_wykonania TEXT,
                status TEXT NOT NULL DEFAULT 'zalecona' CHECK(status IN ('zalecona','wykonana','anulowana')),
                komentarz TEXT)"""),
            ("ebr_korekta_v2", """CREATE TABLE ebr_korekta_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sesja_id INTEGER NOT NULL REFERENCES ebr_etap_sesja(id),
                korekta_typ_id INTEGER NOT NULL REFERENCES etap_korekty_katalog(id),
                ilosc REAL, zalecil TEXT, wykonawca_info TEXT,
                dt_zalecenia TEXT, dt_wykonania TEXT,
                status TEXT NOT NULL DEFAULT 'zalecona' CHECK(status IN ('zalecona','wykonana','anulowana')),
                zlecenie_id INTEGER REFERENCES ebr_korekta_zlecenie(id),
                ilosc_wyliczona REAL)"""),
            ("ebr_pomiar", """CREATE TABLE ebr_pomiar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sesja_id INTEGER NOT NULL REFERENCES ebr_etap_sesja(id),
                parametr_id INTEGER NOT NULL REFERENCES parametry_analityczne(id),
                wartosc REAL, min_limit REAL, max_limit REAL,
                w_limicie INTEGER, is_manual INTEGER NOT NULL DEFAULT 1,
                dt_wpisu TEXT NOT NULL, wpisal TEXT NOT NULL,
                odziedziczony INTEGER DEFAULT 0,
                UNIQUE(sesja_id, parametr_id))"""),
        ]:
            fks = conn.execute(f"PRAGMA foreign_key_list({tbl})").fetchall()
            if any("_old" in str(fk) or "_v2_old" in str(fk) or "_fix" in str(fk) for fk in fks):
                print(f"  Rebuilding {tbl} (stale FK)…")
                conn.executescript(f"""
                    PRAGMA foreign_keys = OFF;
                    ALTER TABLE {tbl} RENAME TO _{tbl}_fk_fix;
                    {ddl};
                    INSERT INTO {tbl} SELECT * FROM _{tbl}_fk_fix;
                    DROP TABLE _{tbl}_fk_fix;
                """)
        # Re-enable FK enforcement
        conn.execute("PRAGMA foreign_keys = ON")
        print("ebr_etap_sesja rebuild done")
    else:
        print("ebr_etap_sesja CHECK already up to date")

    conn.commit()

    # ── 7. Seed etap_decyzje ──────────────────────────────────
    # Look up etap IDs by kod
    etap_rows = conn.execute(
        "SELECT id, kod FROM etapy_analityczne WHERE kod IN ('sulfonowanie','utlenienie','standaryzacja')"
    ).fetchall()
    etap_map = {r["kod"]: r["id"] for r in etap_rows}

    missing = {"sulfonowanie", "utlenienie", "standaryzacja"} - set(etap_map)
    if missing:
        print(f"WARNING: etapy_analityczne missing stages: {missing} — skipping seed")
    else:
        produkty = ["K7", "K40GL", "K40GLO", "K40GLOL"]

        # Decision definitions per stage: (typ, kod, label, akcja, wymaga_komentarza, kolejnosc)
        decisions = {
            "sulfonowanie": [
                ("pass", "next_stage",      "Przejdź do utleniania",        "next_stage",    0, 1),
                ("fail", "new_round",        "Nowa runda",                   "new_round",     0, 2),
            ],
            "utlenienie": [
                ("pass", "next_stage",      "Przejdź do standaryzacji",     "next_stage",    0, 1),
                ("fail", "new_round",        "Nowa runda",                   "new_round",     0, 2),
                ("fail", "skip_to_next",     "Przenieś korektę do standaryzacji", "skip_to_next", 0, 3),
            ],
            "standaryzacja": [
                ("pass", "release",          "Zatwierdź szarżę",            "release",       0, 1),
                ("fail", "new_round",        "Kolejna runda (korekta)",      "new_round",     0, 2),
                ("fail", "release_comment",  "Zwolnij z komentarzem",        "release",       1, 3),
                ("fail", "close_note",       "Zamknij z notatką",            "close",         1, 4),
            ],
        }

        seeded = 0
        for produkt in produkty:
            for etap_kod, decs in decisions.items():
                etap_id = etap_map[etap_kod]
                for typ, kod, label, akcja, wymaga, kolejnosc in decs:
                    exists = conn.execute(
                        "SELECT 1 FROM etap_decyzje WHERE etap_id=? AND produkt=? AND kod=?",
                        (etap_id, produkt, kod),
                    ).fetchone()
                    if not exists:
                        conn.execute(
                            "INSERT INTO etap_decyzje (etap_id, produkt, typ, kod, label, akcja, wymaga_komentarza, kolejnosc)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (etap_id, produkt, typ, kod, label, akcja, wymaga, kolejnosc),
                        )
                        seeded += 1
        conn.commit()
        print(f"Seeded {seeded} etap_decyzje rows")

    # ── 8. Seed etap_warunki for SO₃²⁻ and H₂O₂ gates ───────
    param_rows = conn.execute(
        "SELECT id, kod FROM parametry_analityczne WHERE kod IN ('so3','h2o2')"
    ).fetchall()
    param_map = {r["kod"]: r["id"] for r in param_rows}

    missing_params = {"so3", "h2o2"} - set(param_map)
    if missing_params:
        print(f"WARNING: parametry_analityczne missing: {missing_params} — skipping gate seed")
    else:
        gates = []
        if "sulfonowanie" in etap_map:
            gates.append((etap_map["sulfonowanie"], param_map["so3"], "<=", 0.1,
                          "SO₃²⁻ ≤ 0.1"))
        if "utlenienie" in etap_map:
            gates.append((etap_map["utlenienie"], param_map["so3"], "<=", 0.1,
                          "SO₃²⁻ ≤ 0.1"))
            gates.append((etap_map["utlenienie"], param_map["h2o2"], "<=", 0.1,
                          "H₂O₂ ≤ 0.1"))

        seeded_gates = 0
        for etap_id, parametr_id, operator, wartosc, opis in gates:
            exists = conn.execute(
                "SELECT 1 FROM etap_warunki WHERE etap_id=? AND parametr_id=?",
                (etap_id, parametr_id),
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO etap_warunki (etap_id, parametr_id, operator, wartosc, opis_warunku)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (etap_id, parametr_id, operator, wartosc, opis),
                )
                seeded_gates += 1
        conn.commit()
        print(f"Seeded {seeded_gates} etap_warunki gate rows")

    conn.close()
    print("OK — batch card V2 migration complete")


if __name__ == "__main__":
    main()
