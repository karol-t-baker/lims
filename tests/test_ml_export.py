"""Tests for ML export — long format (zip with CSVs + schema.json)."""
import io
import json
import sqlite3
import zipfile

import pytest

from mbr.models import init_mbr_tables


def _seed_k7(conn: sqlite3.Connection) -> None:
    """Minimal K7 pipeline fixture: 1 completed batch, sesje on 3 stages, legacy recipe."""
    conn.execute("DELETE FROM mbr_templates")
    conn.execute("DELETE FROM produkt_pipeline")
    conn.execute("DELETE FROM etap_parametry")
    conn.execute("DELETE FROM korekta_cele")
    conn.execute("DELETE FROM etap_korekty_katalog")
    conn.execute("DELETE FROM etapy_analityczne")
    conn.execute("DELETE FROM parametry_analityczne")
    conn.execute("DELETE FROM produkty")
    params = [
        (1, 'ph_10proc', 'pH 10%',             'bezposredni', 2, None,             None),
        (2, 'nd20',      'nD20',               'bezposredni', 4, None,             None),
        (3, 'so3',       'Siarczyny',          'titracja',    3, None,             '%'),
        (4, 'barwa_I2',  'Barwa jodowa',       'bezposredni', 2, None,             None),
        (5, 'nadtlenki', 'Nadtlenki',          'titracja',    3, None,             '%'),
        (6, 'sm',        'Sucha masa',         'bezposredni', 1, None,             '%'),
        (7, 'nacl',      'Chlorek sodu',       'titracja',    1, None,             '%'),
        (8, 'sa',        'Substancja aktywna', 'obliczeniowy',1, 'sm - nacl - 0.6', '%'),
        (9, 'na2so3_recept_kg', 'Siarczyn sodu — recepta', 'bezposredni', 2, None, 'kg'),
    ]
    for p in params:
        conn.execute(
            """INSERT INTO parametry_analityczne
                   (id, kod, label, typ, precision, formula, jednostka)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            p,
        )
    conn.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (4,'sulfonowanie','Sulfonowanie','jednorazowy')")
    conn.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (5,'utlenienie','Utlenienie','cykliczny')")
    conn.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (9,'standaryzacja','Standaryzacja','cykliczny')")
    conn.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (10,'analiza_koncowa','Analiza końcowa','jednorazowy')")
    for etap_id, k in [(4,1),(5,2),(9,3),(10,4)]:
        conn.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chegina_K7',?,?)", (etap_id, k))
    for etap_id, param_id in [
        (4,1),(4,2),(4,3),(4,4),
        (5,1),(5,2),(5,3),(5,4),(5,5),
        (9,1),(9,2),(9,6),(9,7),(9,8),
        (10,1),(10,4),(10,6),(10,7),(10,8),
    ]:
        conn.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (?, ?, 1)", (etap_id, param_id))
    for kid, etap_id, subst in [
        (1,4,'Siarczyn sodu'), (2,4,'Perhydrol 34%'),
        (3,5,'Perhydrol 34%'), (4,5,'Woda łącznie'), (5,5,'Kwas cytrynowy'),
        (6,9,'Woda łącznie'),
    ]:
        conn.execute("INSERT INTO etap_korekty_katalog (id, etap_id, substancja, jednostka) VALUES (?, ?, ?, 'kg')",
                     (kid, etap_id, subst))
    parametry_lab = {
        "analiza_koncowa": {
            "pola": [
                {"kod": "ph_10proc", "min_limit": 4.0, "max_limit": 6.0},
                {"kod": "sm",        "min_limit": 40.0, "max_limit": 48.0},
                {"kod": "sa",        "min_limit": 30.0, "max_limit": 42.0, "formula": "sm - nacl - 0.6"},
                {"kod": "barwa_I2",  "min_limit": 0.0, "max_limit": 200.0},
            ]
        }
    }
    conn.execute(
        "INSERT INTO mbr_templates (mbr_id, produkt, wersja, parametry_lab, dt_utworzenia) "
        "VALUES (1,'Chegina_K7',1,?,'2026-01-01')",
        (json.dumps(parametry_lab),),
    )
    # Per-stage product specs (some of them)
    conn.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, min_limit, max_limit) "
        "VALUES ('Chegina_K7', 10, 4, 0.0, 200.0)"
    )
    conn.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, min_limit, max_limit) "
        "VALUES ('Chegina_K7', 10, 8, 30.0, 42.0)"
    )

    conn.execute(
        """INSERT INTO ebr_batches
               (ebr_id, mbr_id, batch_id, nr_partii, wielkosc_szarzy_kg, nastaw,
                dt_start, dt_end, status, typ, pakowanie_bezposrednie)
           VALUES (1, 1, 'Chegina_K7__1_2026', '1/2026', 13300, 13300,
                   '2026-04-16T09:00:00', '2026-04-16T12:00:00', 'completed', 'szarza', NULL)"""
    )
    # Legacy recipe dose (ebr_wyniki only)
    conn.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc, dt_wpisu, wpisal) "
        "VALUES (1,'sulfonowanie','na2so3_recept_kg','na2so3',15.0,'2026-04-16','JK')"
    )
    # Sulfonowanie R1 — 4 pomiary + 1 korekta
    conn.execute(
        "INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, decyzja, dt_start, laborant) "
        "VALUES (1,1,4,1,'zamkniety','przejscie','2026-04-16T09:05:00','JK')"
    )
    for pid, val in [(1, 11.89), (2, 1.3954), (3, 0.12), (4, 0.2)]:
        conn.execute(
            "INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) "
            "VALUES (1, ?, ?, 1, '2026-04-16', 'JK')",
            (pid, val),
        )
    conn.execute(
        "INSERT INTO ebr_korekta_v2 (sesja_id, korekta_typ_id, ilosc, status) "
        "VALUES (1,1,15.0,'wykonana')"
    )
    # Targets (globals)
    conn.execute("INSERT INTO korekta_cele (etap_id, produkt, kod, wartosc) VALUES (9,'Chegina_K7','target_ph',6.25)")
    conn.execute("INSERT INTO korekta_cele (etap_id, produkt, kod, wartosc) VALUES (9,'Chegina_K7','target_nd20',1.3922)")


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_mbr_tables(conn)
    _seed_k7(conn)
    conn.commit()
    yield conn
    conn.close()


# Placeholder — real tests added in later tasks.
def test_fixture_smoke(db):
    row = db.execute("SELECT COUNT(*) FROM ebr_batches").fetchone()
    assert row[0] == 1
