"""Regression: K7 process-stage labels clearly mark analytical checkpoints.

The `etapy_analityczne` table holds the user-visible stage labels seen in
the laborant batch card. Its rows are populated by
scripts/migrate_parametry_etapy.py (KONTEKST_META dict). This test verifies
the migration produces 'Analiza po …' labels for the three confusing K7
stages — the 'Sulfonowanie' / 'Utlenienie' / 'Standaryzacja' originals
were ambiguous with the chemical phases themselves and confused operators.
"""

import sqlite3
import pytest


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Create just the tables the migration touches.
    conn.execute(
        """CREATE TABLE parametry_etapy (
               kontekst TEXT, parametr_id INTEGER, kolejnosc INTEGER,
               min_limit REAL, max_limit REAL, nawazka_g REAL,
               precision INTEGER, target REAL, wymagany INTEGER,
               grupa TEXT, formula TEXT, sa_bias REAL, krok INTEGER,
               produkt TEXT
           )"""
    )
    conn.execute(
        """CREATE TABLE etapy_analityczne (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               kod TEXT UNIQUE, nazwa TEXT,
               typ_cyklu TEXT, opis TEXT, kolejnosc_domyslna INTEGER
           )"""
    )
    conn.execute(
        """CREATE TABLE etap_parametry (
               etap_id INTEGER, parametr_id INTEGER, kolejnosc INTEGER,
               min_limit REAL, max_limit REAL, nawazka_g REAL,
               precision INTEGER, spec_value REAL, wymagany INTEGER,
               grupa TEXT, formula TEXT, sa_bias REAL, krok INTEGER,
               UNIQUE(etap_id, parametr_id, krok)
           )"""
    )
    conn.execute(
        """CREATE TABLE produkt_pipeline (
               produkt TEXT, etap_id INTEGER, kolejnosc INTEGER,
               UNIQUE(produkt, etap_id)
           )"""
    )
    conn.execute(
        """CREATE TABLE produkt_etap_limity (
               produkt TEXT, etap_id INTEGER, parametr_id INTEGER,
               min_limit REAL, max_limit REAL, spec_value REAL,
               dla_szarzy INTEGER DEFAULT 1,
               UNIQUE(produkt, etap_id, parametr_id)
           )"""
    )
    # Seed one row per target kontekst so the migration emits one
    # etapy_analityczne row per kontekst.
    for kontekst in ("sulfonowanie", "utlenienie", "standaryzacja",
                     "analiza_koncowa"):
        conn.execute(
            "INSERT INTO parametry_etapy (kontekst, parametr_id, kolejnosc) "
            "VALUES (?, 1, 1)",
            (kontekst,),
        )
    conn.commit()
    yield conn
    conn.close()


def test_k7_stage_nazwa_uses_analiza_po_prefix(db):
    from scripts.migrate_parametry_etapy import migrate_parametry_etapy
    migrate_parametry_etapy(db)
    rows = dict(
        db.execute(
            "SELECT kod, nazwa FROM etapy_analityczne "
            "WHERE kod IN ('sulfonowanie','utlenienie','standaryzacja')"
        ).fetchall()
    )
    assert rows["sulfonowanie"]  == "Analiza po sulfonowaniu"
    assert rows["utlenienie"]    == "Analiza po utlenianiu"
    assert rows["standaryzacja"] == "Analiza po standaryzacji"


def test_analiza_koncowa_label_unchanged(db):
    """4th stage (analiza_koncowa) is already clearly named — keep it."""
    from scripts.migrate_parametry_etapy import migrate_parametry_etapy
    migrate_parametry_etapy(db)
    row = db.execute(
        "SELECT nazwa FROM etapy_analityczne WHERE kod = 'analiza_koncowa'"
    ).fetchone()
    assert row["nazwa"] == "Analiza końcowa"
