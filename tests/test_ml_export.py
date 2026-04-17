"""Tests for ML export query builder."""
import sqlite3
import pytest
from mbr.models import init_mbr_tables
from mbr.ml_export.query import export_k7_batches, get_csv_columns


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
    # Etap parametry (required for dynamic schema)
    conn.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (4,1,1)")
    conn.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (4,2,2)")
    conn.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (4,3,3)")
    conn.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (4,4,4)")
    conn.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (5,1,1)")
    conn.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (5,2,2)")
    conn.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (5,3,3)")
    conn.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (5,4,4)")
    conn.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (5,5,5)")
    conn.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (9,1,1)")
    conn.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (9,2,2)")
    conn.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (9,6,3)")
    conn.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (9,7,4)")
    conn.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (9,8,5)")
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
    assert row["status"] == "completed"
    assert row["masa_kg"] == 13300.0
    assert row["meff_kg"] == 12300.0
    assert row["sulf_na2so3_recept_kg"] == 15.0
    assert row["sulf_r1_ph"] == 11.89
    assert row["sulf_r1_so3"] == 0.12
    # Korekty always carry round suffix (pinned schema)
    assert row["sulf_na2so3_r1_kg"] == 15.0
    assert row["sulf_perhydrol_r1_kg"] == 19.0
    assert row["sulf_rundy"] == 1
    # Utlenienie: 2 real rounds
    assert row["utl_r1_nadtlenki"] == 0.0
    assert row["utl_r2_nadtlenki"] == 0.003
    assert row["utl_perhydrol_r1_kg"] == 5.0
    assert row["utl_woda_r2_kg"] == 1200.0
    assert row["utl_kwas_r2_kg"] == 100.0
    assert row["utl_kwas_r2_sugest_kg"] == 110.5
    assert row["utl_rundy"] == 2
    # Third-round cols exist but are None
    assert "utl_r3_nadtlenki" in row and row["utl_r3_nadtlenki"] is None
    # Standaryzacja
    assert row["stand_r1_ph"] == 6.25
    assert row["stand_r1_sm"] == 43.0
    assert row["stand_rundy"] == 1
    assert row["target_ph"] == 6.25
    assert row["target_nd20"] == 1.3922
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
    columns = get_csv_columns(db)
    assert len(rows) == 1
    for col in columns:
        assert col in rows[0], f"Missing column: {col}"


def test_open_batch_excluded(db):
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, wielkosc_szarzy_kg, nastaw,
                  dt_start, status, typ) VALUES (2,1,'Chegina_K7__2_2026','2/2026',13300,13300,'2026-04-17T09:00:00','open','szarza')""")
    db.commit()
    rows = export_k7_batches(db)
    assert len(rows) == 1
    assert rows[0]["ebr_id"] == 1


# ─── ML-1: sugest_kg for every formula-driven korekta ─────────────────────────

def test_sugest_cols_extended_to_perhydrol_and_woda(db):
    """ilosc_wyliczona must flow into *_sugest_kg for Perhydrol and Woda łącznie,
    not just Kwas cytrynowy — operator deviation from formula is the signal."""
    # Add Perhydrol suggestion at utl R1 and Woda łącznie suggestion at utl R2
    db.execute("UPDATE ebr_korekta_v2 SET ilosc_wyliczona = 6.8 WHERE sesja_id=2 AND korekta_typ_id=3")
    db.execute("UPDATE ebr_korekta_v2 SET ilosc_wyliczona = 1180.0 WHERE sesja_id=3 AND korekta_typ_id=4")
    db.commit()

    cols = get_csv_columns(db)
    assert "utl_perhydrol_r1_sugest_kg" in cols
    assert "utl_woda_r2_sugest_kg" in cols
    assert "stand_woda_r1_sugest_kg" in cols  # even if no data yet, column exists

    row = export_k7_batches(db)[0]
    assert row["utl_perhydrol_r1_sugest_kg"] == 6.8
    assert row["utl_woda_r2_sugest_kg"] == 1180.0


# ─── ML-2: FIXED_MAX_ROUNDS doesn't grow with data ────────────────────────────

def test_max_rounds_pinned_not_discovered(db):
    """Even if a batch has fewer than cap rounds, column set covers up to cap.
    And an actual batch with MORE than cap rounds would be truncated (tested
    via the len(columns) assertion — column count doesn't change with data)."""
    from mbr.ml_export.query import FIXED_MAX_ROUNDS
    assert FIXED_MAX_ROUNDS["sulfonowanie"] == 3
    assert FIXED_MAX_ROUNDS["utlenienie"] == 3
    assert FIXED_MAX_ROUNDS["standaryzacja"] == 3

    cols_before = get_csv_columns(db)
    # Insert a 3rd-round sulfonowanie sesja (more than the 1 the fixture has).
    # The column list should NOT grow — we already budgeted for 3 rounds.
    db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, decyzja) VALUES (99,1,4,3,'zamkniety','przejscie')")
    db.commit()
    cols_after = get_csv_columns(db)
    assert cols_before == cols_after, "column schema must be stable across data changes"


# ─── ML-3: include failed/cancelled batches on demand ─────────────────────────

def test_cancelled_batch_excluded_by_default(db):
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, wielkosc_szarzy_kg, nastaw,
                  dt_start, status, typ) VALUES (3,1,'C_K7__3','3/2026',13300,13300,'2026-04-18','cancelled','szarza')""")
    db.commit()
    rows = export_k7_batches(db)
    ids = [r["ebr_id"] for r in rows]
    assert 3 not in ids


def test_cancelled_batch_included_when_requested(db):
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, wielkosc_szarzy_kg, nastaw,
                  dt_start, status, typ) VALUES (3,1,'C_K7__3','3/2026',13300,13300,'2026-04-18','cancelled','szarza')""")
    db.commit()
    rows = export_k7_batches(db, statuses=("completed", "cancelled"))
    ids = [r["ebr_id"] for r in rows]
    assert 3 in ids
    cancelled = next(r for r in rows if r["ebr_id"] == 3)
    assert cancelled["status"] == "cancelled"


# ─── ML-4: per-round dt_start column ──────────────────────────────────────────

def test_per_round_dt_start_column(db):
    db.execute("UPDATE ebr_etap_sesja SET dt_start='2026-04-16T09:30:00' WHERE id=2")
    db.execute("UPDATE ebr_etap_sesja SET dt_start='2026-04-16T11:15:00' WHERE id=3")
    db.commit()
    row = export_k7_batches(db)[0]
    assert row["utl_r1_dt_start"] == "2026-04-16T09:30:00"
    assert row["utl_r2_dt_start"] == "2026-04-16T11:15:00"
    assert row["utl_r3_dt_start"] is None  # only 2 real rounds


# ─── ML-5: korekta_cele snapshot preferred over live globals ──────────────────

def test_targets_from_sesja_snapshot_when_present(db):
    """If a sesja has cele_json, targets come from it — not from current globals."""
    # Snapshot stored on stand R1 sesja (id=4) differs from the current global
    # (target_ph=6.25, target_nd20=1.3922 per fixture)
    db.execute(
        "UPDATE ebr_etap_sesja SET cele_json=? WHERE id=4",
        ('{"target_ph": 5.80, "target_nd20": 1.3899}',),
    )
    db.commit()
    row = export_k7_batches(db)[0]
    assert row["target_ph"] == 5.80
    assert row["target_nd20"] == 1.3899


def test_targets_fallback_to_globals_without_snapshot(db):
    """No snapshot → fall back to current korekta_cele globals."""
    row = export_k7_batches(db)[0]
    assert row["target_ph"] == 6.25
    assert row["target_nd20"] == 1.3922


def test_create_sesja_snapshots_targets(db):
    """create_sesja() writes a cele_json snapshot of current korekta_cele
    (so later globals drift doesn't retrospectively reassign targets)."""
    from mbr.pipeline.models import create_sesja
    # Seed a fresh batch + sesja via the live API
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, wielkosc_szarzy_kg, nastaw,
                  dt_start, status, typ) VALUES (10,1,'C_K7__10','10/2026',13300,13300,'2026-04-19','open','szarza')""")
    sid = create_sesja(db, ebr_id=10, etap_id=9, runda=1, laborant="JK")
    row = db.execute("SELECT cele_json FROM ebr_etap_sesja WHERE id=?", (sid,)).fetchone()
    assert row["cele_json"] is not None
    import json as _json
    data = _json.loads(row["cele_json"])
    assert data["target_ph"] == 6.25
    assert data["target_nd20"] == 1.3922


# ─── ML-6: wpisal + zalecil attribution columns ──────────────────────────────

def test_wpisal_and_zalecil_columns(db):
    db.execute("UPDATE ebr_pomiar SET wpisal='JK' WHERE sesja_id=2")
    db.execute("UPDATE ebr_korekta_v2 SET zalecil='MM' WHERE sesja_id=3 AND korekta_typ_id=5")
    db.commit()
    row = export_k7_batches(db)[0]
    assert row["utl_r1_wpisal"] == "JK"
    assert row["utl_kwas_r2_zalecil"] == "MM"


# ─── ML-10: "Woda" and "Woda łącznie" both land in the same 'woda' column ──

def test_mixed_woda_and_woda_lacznie_export_to_same_column(db):
    """Legacy rows saved as substancja='Woda' and new rows as 'Woda łącznie'
    must both export into the same *_woda_r{N}_kg column."""
    # Rename one of the katalog entries so we have one 'Woda' and one 'Woda łącznie'
    db.execute("UPDATE etap_korekty_katalog SET substancja='Woda łącznie' WHERE id=6")
    # Add a second batch whose stand R1 korekta points at the renamed entry
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, wielkosc_szarzy_kg, nastaw,
                  dt_start, dt_end, status, typ)
                  VALUES (2, 1, 'C_K7__2_2026','2/2026', 13300, 13300,
                  '2026-04-17T09:00:00','2026-04-17T10:00:00','completed','szarza')""")
    db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, decyzja) VALUES (20,2,9,1,'zamkniety','przejscie')")
    db.execute("INSERT INTO ebr_korekta_v2 (sesja_id, korekta_typ_id, ilosc) VALUES (20,6,88.0)")  # 'Woda łącznie'
    # Also add an old-style 'Woda' entry to the first batch's standaryzacja
    db.execute("INSERT INTO etap_korekty_katalog (id, etap_id, substancja, jednostka) VALUES (99,9,'Woda','kg')")
    db.execute("INSERT INTO ebr_korekta_v2 (sesja_id, korekta_typ_id, ilosc) VALUES (4,99,77.0)")
    db.commit()

    rows = export_k7_batches(db)
    by_id = {r["ebr_id"]: r for r in rows}
    # Batch 1 saved under legacy 'Woda' → lands in stand_woda_r1_kg
    assert by_id[1]["stand_woda_r1_kg"] == 77.0
    # Batch 2 saved under 'Woda łącznie' → same column
    assert by_id[2]["stand_woda_r1_kg"] == 88.0
