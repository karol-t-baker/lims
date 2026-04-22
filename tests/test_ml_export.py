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


# ─── schema.py ────────────────────────────────────────────────────────────────

def test_build_schema_structure(db):
    from mbr.ml_export.schema import build_schema
    s = build_schema(db, produkty=["Chegina_K7"], counts={"batches": 1, "sessions": 1, "measurements": 4, "corrections": 1})
    assert s["export_version"] == "1.0"
    assert s["produkt_filter"] == ["Chegina_K7"]
    assert s["counts"]["batches"] == 1
    # generated_at is ISO-ish
    assert "T" in s["generated_at"]
    # etapy in pipeline order
    kody = [e["kod"] for e in s["etapy"]]
    assert kody == ["sulfonowanie", "utlenienie", "standaryzacja", "analiza_koncowa"]


def test_build_schema_parametry_dict(db):
    from mbr.ml_export.schema import build_schema
    s = build_schema(db, produkty=["Chegina_K7"])
    # sa is calculated with a formula
    sa = s["parametry"]["sa"]
    assert sa["is_calculated"] is True
    assert sa["formula"] == "sm - nacl - 0.6"
    assert sa["jednostka"] == "%"
    # sa appears in analiza_koncowa.parametry_lab with min/max → target candidate
    assert sa["is_target_candidate"] is True
    # nd20 is not a target candidate (not in analiza_koncowa parametry_lab)
    assert s["parametry"]["nd20"]["is_target_candidate"] is False


def test_build_schema_recipe_kategoria(db):
    from mbr.ml_export.schema import build_schema
    s = build_schema(db, produkty=["Chegina_K7"])
    assert s["parametry"]["na2so3_recept_kg"]["kategoria"] == "recipe"
    assert s["parametry"]["sm"]["kategoria"] == "measurement"


def test_build_schema_per_stage_specs(db):
    from mbr.ml_export.schema import build_schema
    s = build_schema(db, produkty=["Chegina_K7"])
    barwa = s["parametry"]["barwa_I2"]
    assert barwa["specs_per_etap"]["analiza_koncowa"] == {"min": 0.0, "max": 200.0}


def test_build_schema_substancje(db):
    from mbr.ml_export.schema import build_schema
    s = build_schema(db, produkty=["Chegina_K7"])
    subs = s["substancje_korekcji"]
    assert "Perhydrol 34%" in subs
    assert "Woda łącznie" in subs
    # Formula-driven via etap_korekty_katalog.formula_ilosc OR ilosc_wyliczona — none seeded here,
    # so all default to False. (test_build_schema_substancje_formula verifies is_formula_driven=True path.)
    assert subs["Perhydrol 34%"]["is_formula_driven"] is False


def test_build_schema_substancje_formula(db):
    """is_formula_driven=True when etap_korekty_katalog.formula_ilosc is non-empty."""
    from mbr.ml_export.schema import build_schema
    # Seed Kwas cytrynowy (id=5 already exists in fixture, katalog id=5) with formula_ilosc
    db.execute(
        "UPDATE etap_korekty_katalog SET formula_ilosc=? WHERE substancja=?",
        ("100 * (ph - target) / masa", "Kwas cytrynowy"),
    )
    # Siarczyn sodu (id=1) keeps formula_ilosc=NULL
    db.commit()
    s = build_schema(db, produkty=["Chegina_K7"])
    subs = s["substancje_korekcji"]
    assert subs["Kwas cytrynowy"]["is_formula_driven"] is True
    assert subs["Siarczyn sodu"]["is_formula_driven"] is False


# ─── build_batches ────────────────────────────────────────────────────────────

BATCH_COLS = {
    "ebr_id", "batch_id", "nr_partii", "produkt", "status",
    "masa_kg", "meff_kg", "dt_start", "dt_end", "pakowanie",
    "target_ph", "target_nd20",
}


def test_build_batches_one_row(db):
    from mbr.ml_export.query import build_batches
    rows = build_batches(db, produkty=["Chegina_K7"], statuses=("completed",))
    assert len(rows) == 1
    r = rows[0]
    assert set(r.keys()) == BATCH_COLS
    assert r["ebr_id"] == 1
    assert r["batch_id"] == "Chegina_K7__1_2026"
    assert r["produkt"] == "Chegina_K7"
    assert r["status"] == "completed"
    assert r["masa_kg"] == 13300.0
    assert r["meff_kg"] == 12300.0  # masa > 6600 → masa - 1000
    assert r["pakowanie"] == "zbiornik"  # default when NULL in DB
    assert r["target_ph"] == 6.25
    assert r["target_nd20"] == 1.3922


def test_build_batches_meff_below_threshold(db):
    from mbr.ml_export.query import build_batches
    db.execute("UPDATE ebr_batches SET wielkosc_szarzy_kg=5000, nastaw=5000 WHERE ebr_id=1")
    db.commit()
    r = build_batches(db, produkty=["Chegina_K7"], statuses=("completed",))[0]
    assert r["masa_kg"] == 5000.0
    assert r["meff_kg"] == 4500.0  # masa <= 6600 → masa - 500


def test_build_batches_status_filter(db):
    from mbr.ml_export.query import build_batches
    db.execute(
        """INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, wielkosc_szarzy_kg,
                                     nastaw, dt_start, status, typ)
           VALUES (2,1,'K7__2','2/2026',13300,13300,'2026-04-17','cancelled','szarza')"""
    )
    db.commit()
    assert len(build_batches(db, produkty=["Chegina_K7"], statuses=("completed",))) == 1
    rows = build_batches(db, produkty=["Chegina_K7"], statuses=("completed","cancelled"))
    assert {r["ebr_id"] for r in rows} == {1, 2}


def test_build_batches_target_from_snapshot(db):
    """cele_json on any standaryzacja session overrides globals."""
    from mbr.ml_export.query import build_batches
    db.execute(
        "INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, cele_json) "
        "VALUES (99, 1, 9, 1, 'zamkniety', ?)",
        ('{"target_ph": 5.80, "target_nd20": 1.3899}',),
    )
    db.commit()
    r = build_batches(db, produkty=["Chegina_K7"], statuses=("completed",))[0]
    assert r["target_ph"] == 5.80
    assert r["target_nd20"] == 1.3899


def test_build_batches_open_excluded(db):
    from mbr.ml_export.query import build_batches
    db.execute(
        """INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, wielkosc_szarzy_kg,
                                     nastaw, dt_start, status, typ)
           VALUES (5,1,'K7__5','5/2026',13300,13300,'2026-04-17','open','szarza')"""
    )
    db.commit()
    rows = build_batches(db, produkty=["Chegina_K7"], statuses=("completed","cancelled"))
    assert all(r["status"] in ("completed","cancelled") for r in rows)


# ─── build_sessions ───────────────────────────────────────────────────────────

def test_build_sessions_from_seed(db):
    from mbr.ml_export.query import build_sessions
    rows = build_sessions(db, ebr_ids=[1])
    assert len(rows) == 1
    s = rows[0]
    assert set(s.keys()) == {"ebr_id", "etap", "runda", "dt_start", "laborant"}
    assert s == {
        "ebr_id": 1,
        "etap": "sulfonowanie",
        "runda": 1,
        "dt_start": "2026-04-16T09:05:00",
        "laborant": "JK",
    }


def test_build_sessions_multiple_stages_ordered(db):
    """Sessions ordered by (ebr_id, etap pipeline order, runda)."""
    from mbr.ml_export.query import build_sessions
    # Add utlenienie R1 and R2
    db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, dt_start, laborant) "
               "VALUES (2,1,5,1,'zamkniety','2026-04-16T10:00:00','JK')")
    db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, dt_start, laborant) "
               "VALUES (3,1,5,2,'zamkniety','2026-04-16T10:30:00','JK')")
    db.commit()
    rows = build_sessions(db, ebr_ids=[1])
    assert [(r["etap"], r["runda"]) for r in rows] == [
        ("sulfonowanie", 1), ("utlenienie", 1), ("utlenienie", 2),
    ]


def test_build_sessions_empty_when_no_ids(db):
    from mbr.ml_export.query import build_sessions
    assert build_sessions(db, ebr_ids=[]) == []


# ─── build_measurements ───────────────────────────────────────────────────────

MEAS_COLS = {
    "ebr_id", "etap", "runda", "param_kod",
    "wartosc", "wartosc_text", "w_limicie",
    "dt_wpisu", "wpisal", "is_legacy",
}


def test_build_measurements_new_only(db):
    """Fixture: sulfonowanie R1 has 4 pomiary in ebr_pomiar, no ebr_wyniki for them."""
    from mbr.ml_export.query import build_measurements
    rows = build_measurements(db, ebr_ids=[1])
    # 4 pomiary + 1 legacy na2so3_recept_kg (always exempt) = 5
    assert len(rows) == 5
    new = [r for r in rows if r["is_legacy"] == 0]
    assert len(new) == 4
    for r in new:
        assert set(r.keys()) == MEAS_COLS
        assert r["ebr_id"] == 1
        assert r["etap"] == "sulfonowanie"
        assert r["runda"] == 1
        assert r["wartosc"] is not None
        assert r["w_limicie"] == 1
        assert r["wpisal"] == "JK"
    by_param = {r["param_kod"]: r["wartosc"] for r in new}
    assert by_param["ph_10proc"] == 11.89
    assert by_param["so3"] == 0.12


def test_build_measurements_recipe_always_legacy(db):
    """na2so3_recept_kg is always emitted from ebr_wyniki with runda=0, is_legacy=1,
    even when ebr_pomiar has the same param."""
    from mbr.ml_export.query import build_measurements
    rows = build_measurements(db, ebr_ids=[1])
    legacy = [r for r in rows if r["is_legacy"] == 1]
    recipe = [r for r in legacy if r["param_kod"] == "na2so3_recept_kg"]
    assert len(recipe) == 1
    r = recipe[0]
    assert r["runda"] == 0
    assert r["etap"] == "sulfonowanie"
    assert r["wartosc"] == 15.0


def test_build_measurements_legacy_only_emitted(db):
    """Legacy value for (etap, param) with no corresponding pomiar → emit with runda=0."""
    from mbr.ml_export.query import build_measurements
    # Insert legacy SM in analiza_koncowa — no session, no pomiar
    db.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc, w_limicie, dt_wpisu, wpisal) "
        "VALUES (1,'analiza_koncowa','sm','sm',43.5,1,'2026-04-16','JK')"
    )
    db.commit()
    rows = build_measurements(db, ebr_ids=[1])
    leg_sm = [r for r in rows if r["param_kod"] == "sm" and r["is_legacy"] == 1]
    assert len(leg_sm) == 1
    assert leg_sm[0]["runda"] == 0
    assert leg_sm[0]["etap"] == "analiza_koncowa"
    assert leg_sm[0]["wartosc"] == 43.5


def test_build_measurements_legacy_suppressed_when_new_exists(db):
    """Legacy value for same (ebr_id, etap, param) as a new pomiar → NOT emitted."""
    from mbr.ml_export.query import build_measurements
    # Fixture: sulfonowanie/ph_10proc exists in ebr_pomiar (sesja_id=1, parametr_id=1)
    # Add legacy entry for the same (ebr_id, etap, param) — should be suppressed
    db.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc, dt_wpisu, wpisal) "
        "VALUES (1,'sulfonowanie','ph_10proc','ph',99.9,'2026-04-16','X')"
    )
    db.commit()
    rows = build_measurements(db, ebr_ids=[1])
    ph = [r for r in rows if r["param_kod"] == "ph_10proc"]
    assert len(ph) == 1
    assert ph[0]["is_legacy"] == 0
    assert ph[0]["wartosc"] == 11.89  # new value wins


def test_build_measurements_wartosc_text(db):
    """ebr_wyniki.wartosc_text (e.g. FAU '<1') must propagate."""
    from mbr.ml_export.query import build_measurements
    db.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc, wartosc_text, dt_wpisu, wpisal) "
        "VALUES (1,'analiza_koncowa','barwa_I2','barwa',NULL,'<1','2026-04-16','JK')"
    )
    db.commit()
    rows = build_measurements(db, ebr_ids=[1])
    below = [r for r in rows if r["param_kod"] == "barwa_I2" and r["etap"] == "analiza_koncowa"]
    assert len(below) == 1
    assert below[0]["wartosc"] is None
    assert below[0]["wartosc_text"] == "<1"
    assert below[0]["is_legacy"] == 1


# ─── build_corrections ────────────────────────────────────────────────────────

CORR_COLS = {
    "ebr_id", "etap", "runda", "substancja",
    "kg", "sugest_kg", "status", "zalecil", "dt_wykonania",
}


def test_build_corrections_basic(db):
    from mbr.ml_export.query import build_corrections
    rows = build_corrections(db, ebr_ids=[1])
    # Fixture has 1 Siarczyn sodu correction on sulfonowanie R1
    assert len(rows) == 1
    r = rows[0]
    assert set(r.keys()) == CORR_COLS
    assert r["ebr_id"] == 1
    assert r["etap"] == "sulfonowanie"
    assert r["runda"] == 1
    assert r["substancja"] == "Siarczyn sodu"
    assert r["kg"] == 15.0
    assert r["status"] == "wykonana"
    assert r["sugest_kg"] is None


def test_build_corrections_with_suggestion(db):
    """ilosc_wyliczona flows into sugest_kg."""
    from mbr.ml_export.query import build_corrections
    # Utlenienie R1 session + Kwas cytrynowy correction with suggestion
    db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, laborant) "
               "VALUES (7,1,5,1,'zamkniety','JK')")
    db.execute("INSERT INTO ebr_korekta_v2 (sesja_id, korekta_typ_id, ilosc, ilosc_wyliczona, status, zalecil, dt_wykonania) "
               "VALUES (7, 5, 100.0, 110.5, 'wykonana', 'MM', '2026-04-16T10:15:00')")
    db.commit()
    rows = build_corrections(db, ebr_ids=[1])
    kwas = [r for r in rows if r["substancja"] == "Kwas cytrynowy"][0]
    assert kwas["kg"] == 100.0
    assert kwas["sugest_kg"] == 110.5
    assert kwas["zalecil"] == "MM"
    assert kwas["dt_wykonania"] == "2026-04-16T10:15:00"


def test_build_corrections_all_statuses_emitted(db):
    """Anulowana and zalecona are also emitted — client filters."""
    from mbr.ml_export.query import build_corrections
    db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, laborant) "
               "VALUES (8,1,5,2,'zamkniety','JK')")
    db.execute("INSERT INTO ebr_korekta_v2 (sesja_id, korekta_typ_id, ilosc, status) "
               "VALUES (8, 3, 7.0, 'anulowana')")
    db.commit()
    rows = build_corrections(db, ebr_ids=[1])
    statuses = {r["status"] for r in rows}
    assert "anulowana" in statuses
    assert "wykonana" in statuses


# ─── export_ml_package ────────────────────────────────────────────────────────

def _read_zip(blob: bytes) -> dict:
    zf = zipfile.ZipFile(io.BytesIO(blob))
    return {name: zf.read(name).decode("utf-8") for name in zf.namelist()}


def test_export_ml_package_contents(db):
    from mbr.ml_export.query import export_ml_package
    blob = export_ml_package(db)
    files = _read_zip(blob)
    assert set(files.keys()) == {
        "batches.csv", "sessions.csv", "measurements.csv",
        "corrections.csv", "schema.json", "README.md",
    }
    # Schema is valid JSON
    schema = json.loads(files["schema.json"])
    assert schema["counts"]["batches"] == 1
    assert schema["counts"]["sessions"] == 1  # only sulfonowanie R1 in seed
    # Measurements count = 4 new + 1 legacy recipe = 5
    assert schema["counts"]["measurements"] == 5
    # CSV headers present
    assert files["batches.csv"].startswith("ebr_id,batch_id,")
    assert "ebr_id,etap,runda,param_kod" in files["measurements.csv"]


def test_export_ml_package_empty_db(db):
    """Empty K7 — still returns valid zip with 6 files, headers only."""
    from mbr.ml_export.query import export_ml_package
    db.execute("DELETE FROM ebr_korekta_v2")
    db.execute("DELETE FROM ebr_pomiar")
    db.execute("DELETE FROM ebr_wyniki")
    db.execute("DELETE FROM ebr_etap_sesja")
    db.execute("DELETE FROM ebr_batches")
    db.commit()
    blob = export_ml_package(db)
    files = _read_zip(blob)
    assert set(files.keys()) == {
        "batches.csv", "sessions.csv", "measurements.csv",
        "corrections.csv", "schema.json", "README.md",
    }
    # Headers only — each CSV has exactly one line
    assert files["batches.csv"].count("\n") == 1
    assert files["sessions.csv"].count("\n") == 1


def test_export_ml_package_status_filter(db):
    from mbr.ml_export.query import export_ml_package
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii,
                  wielkosc_szarzy_kg, nastaw, dt_start, status, typ)
                  VALUES (2,1,'K7__2','2/2026',13300,13300,'2026-04-17','cancelled','szarza')""")
    db.commit()
    # Default: only completed
    schema_default = json.loads(_read_zip(export_ml_package(db))["schema.json"])
    assert schema_default["counts"]["batches"] == 1
    # With cancelled
    schema_inc = json.loads(_read_zip(export_ml_package(db, statuses=("completed", "cancelled")))["schema.json"])
    assert schema_inc["counts"]["batches"] == 2


def test_export_pandas_pivot_roundtrip(db):
    """Smoke test: round-trip long format through pandas pivot to wide.
    Skipped if pandas not installed (dev env).
    """
    pd = pytest.importorskip("pandas")
    from mbr.ml_export.query import export_ml_package
    files = _read_zip(export_ml_package(db))
    m = pd.read_csv(io.StringIO(files["measurements.csv"]))
    wide = m[m.param_kod == "ph_10proc"].pivot_table(
        index="ebr_id", columns=["etap", "runda"], values="wartosc"
    )
    assert wide.loc[1, ("sulfonowanie", 1)] == 11.89
