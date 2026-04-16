"""Tests for ML export query builder."""
import sqlite3
import pytest
from mbr.models import init_mbr_tables
from mbr.ml_export.query import export_k7_batches, CSV_COLUMNS


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_mbr_tables(conn)
    conn.execute("DELETE FROM parametry_analityczne")
    conn.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (1,'ph_10proc','pH 10%','bezposredni')")
    conn.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (2,'nd20','nD20','bezposredni')")
    conn.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (3,'so3','SO3','titracja')")
    conn.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (4,'barwa_I2','Barwa','bezposredni')")
    conn.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (5,'nadtlenki','Nadtlenki','titracja')")
    conn.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (6,'sm','SM','bezposredni')")
    conn.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (7,'nacl','NaCl','titracja')")
    conn.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (8,'sa','SA','obliczeniowy')")
    conn.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (4,'sulfonowanie','Sulfonowanie','jednorazowy')")
    conn.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (5,'utlenienie','Utlenienie','cykliczny')")
    conn.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (9,'standaryzacja','Standaryzacja','cykliczny')")
    conn.execute("INSERT INTO etap_korekty_katalog (id, etap_id, substancja, jednostka) VALUES (1,4,'Siarczyn sodu','kg')")
    conn.execute("INSERT INTO etap_korekty_katalog (id, etap_id, substancja, jednostka) VALUES (2,4,'Perhydrol 34%','kg')")
    conn.execute("INSERT INTO etap_korekty_katalog (id, etap_id, substancja, jednostka) VALUES (3,5,'Perhydrol 34%','kg')")
    conn.execute("INSERT INTO etap_korekty_katalog (id, etap_id, substancja, jednostka) VALUES (4,5,'Woda','kg')")
    conn.execute("INSERT INTO etap_korekty_katalog (id, etap_id, substancja, jednostka) VALUES (5,5,'Kwas cytrynowy','kg')")
    conn.execute("INSERT INTO etap_korekty_katalog (id, etap_id, substancja, jednostka) VALUES (6,9,'Woda','kg')")
    conn.execute("INSERT INTO etap_korekty_katalog (id, etap_id, substancja, jednostka) VALUES (7,9,'Kwas cytrynowy','kg')")
    conn.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chegina_K7',4,1)")
    conn.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chegina_K7',5,2)")
    conn.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chegina_K7',9,3)")
    conn.execute("INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia) VALUES (1,'Chegina_K7',1,'2026-01-01')")
    conn.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, wielkosc_szarzy_kg, nastaw,
                    dt_start, dt_end, status, typ)
                    VALUES (1, 1, 'Chegina_K7__1_2026', '1/2026', 13300, 13300,
                    '2026-04-16T09:00:00', '2026-04-16T10:00:00', 'completed', 'szarza')""")
    conn.execute("INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc, dt_wpisu, wpisal) VALUES (1,'sulfonowanie','na2so3_recept_kg','na2so3',15.0,'2026-04-16','test')")
    # Sulfonowanie R1
    conn.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, decyzja) VALUES (1,1,4,1,'zamkniety','przejscie')")
    _DT = '2026-04-16'
    _WHO = 'test'
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (1,1,11.89,1,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (1,2,1.3954,1,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (1,3,0.12,1,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (1,4,0.2,1,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_korekta_v2 (sesja_id, korekta_typ_id, ilosc) VALUES (1,1,15.0)")
    conn.execute("INSERT INTO ebr_korekta_v2 (sesja_id, korekta_typ_id, ilosc) VALUES (1,2,19.0)")
    # Utlenienie R1
    conn.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, decyzja) VALUES (2,1,5,1,'zamkniety','new_round')")
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (2,1,11.98,1,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (2,2,1.3982,1,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (2,3,0.0,1,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (2,4,0.21,1,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (2,5,0.0,0,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_korekta_v2 (sesja_id, korekta_typ_id, ilosc) VALUES (2,3,5.0)")
    # Utlenienie R2
    conn.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, decyzja) VALUES (3,1,5,2,'zamkniety','przejscie')")
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (3,1,6.3,1,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (3,2,1.3960,1,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (3,3,0.0,1,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (3,4,0.15,1,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (3,5,0.003,1,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_korekta_v2 (sesja_id, korekta_typ_id, ilosc) VALUES (3,4,1200.0)")
    conn.execute("INSERT INTO ebr_korekta_v2 (sesja_id, korekta_typ_id, ilosc, ilosc_wyliczona) VALUES (3,5,100.0,110.5)")
    # Standaryzacja R1
    conn.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, decyzja) VALUES (4,1,9,1,'zamkniety','przejscie')")
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (4,1,6.25,1,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (4,2,1.3922,1,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (4,6,43.0,1,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (4,7,4.5,1,?,?)", (_DT, _WHO))
    conn.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) VALUES (4,8,37.7,1,?,?)", (_DT, _WHO))
    # Targets
    conn.execute("INSERT INTO korekta_cele (etap_id, produkt, kod, wartosc) VALUES (9,'Chegina_K7','target_ph',6.25)")
    conn.execute("INSERT INTO korekta_cele (etap_id, produkt, kod, wartosc) VALUES (9,'Chegina_K7','target_nd20',1.3922)")
    conn.commit()
    yield conn
    conn.close()


def test_export_returns_all_columns(db):
    rows = export_k7_batches(db)
    assert len(rows) == 1
    row = rows[0]
    assert row["ebr_id"] == 1
    assert row["batch_id"] == "Chegina_K7__1_2026"
    assert row["masa_kg"] == 13300.0
    assert row["meff_kg"] == 12300.0
    assert row["sulf_na2so3_recept_kg"] == 15.0
    assert row["sulf_r1_ph"] == 11.89
    assert row["sulf_r1_so3"] == 0.12
    assert row["sulf_na2so3_kor_kg"] == 15.0
    assert row["sulf_perhydrol_kg"] == 19.0
    assert row["sulf_rundy"] == 1
    assert row["utl_r1_nadtlenki"] == 0.0
    assert row["utl_r2_nadtlenki"] == 0.003
    assert row["utl_perhydrol_r1_kg"] == 5.0
    assert row["utl_woda_kg"] == 1200.0
    assert row["utl_kwas_kg"] == 100.0
    assert row["utl_kwas_sugest_kg"] == 110.5
    assert row["utl_rundy"] == 2
    assert row["stand_r1_ph"] == 6.25
    assert row["stand_r1_sm"] == 43.0
    assert row["stand_rundy"] == 1
    # Targets
    assert row["target_ph"] == 6.25
    assert row["target_nd20"] == 1.3922
    # Final
    assert row["final_ph"] == 6.25
    assert row["final_nd20"] == 1.3922
    assert row["final_all_ok"] == 1


def test_export_incremental(db):
    rows_all = export_k7_batches(db, after_id=0)
    assert len(rows_all) == 1
    rows_none = export_k7_batches(db, after_id=1)
    assert len(rows_none) == 0


def test_csv_columns_match_dict_keys(db):
    rows = export_k7_batches(db)
    assert len(rows) == 1
    for col in CSV_COLUMNS:
        assert col in rows[0], f"Missing column: {col}"


def test_open_batch_excluded(db):
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, wielkosc_szarzy_kg, nastaw,
                  dt_start, status, typ) VALUES (2,1,'Chegina_K7__2_2026','2/2026',13300,13300,'2026-04-17T09:00:00','open','szarza')""")
    db.commit()
    rows = export_k7_batches(db)
    assert len(rows) == 1
    assert rows[0]["ebr_id"] == 1
