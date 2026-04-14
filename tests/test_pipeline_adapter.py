"""
tests/test_pipeline_adapter.py — Tests for mbr/pipeline/adapter.py

Build: TDD — tests written first, then implementation.
"""

import sqlite3
import pytest
from mbr.models import init_mbr_tables


# ---------------------------------------------------------------------------
# Fixture — in-memory DB with pipeline tables seeded
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed(db):
    """
    Seed a cykliczny 'standaryzacja' stage with:
      - sm   (bezposredni)
      - nacl (titracja + metoda_factor)
      - sa   (obliczeniowy + formula)
      - ph   (bezposredni)
    plus warunki, korekty, and product limits for 'TestProd'.
    Uses IDs 9101-9104 to avoid collision with init_mbr_tables seeding.
    """
    # parametry_analityczne
    db.execute("""
        INSERT INTO parametry_analityczne (id, kod, label, typ, skrot, precision,
            metoda_id, metoda_nazwa, metoda_formula, metoda_factor, formula)
        VALUES (9101, 'sm', 'Sucha masa', 'bezposredni', 'SM', 1, NULL, NULL, NULL, NULL, NULL)
    """)
    db.execute("""
        INSERT INTO parametry_analityczne (id, kod, label, typ, skrot, precision,
            metoda_id, metoda_nazwa, metoda_formula, metoda_factor, formula)
        VALUES (9102, 'nacl', 'NaCl', 'titracja', 'NaCl', 2, NULL,
            'Argentometryczna Mohr', '% = (V * 0.00585 * 100) / m', 0.585, NULL)
    """)
    db.execute("""
        INSERT INTO parametry_analityczne (id, kod, label, typ, skrot, precision,
            metoda_id, metoda_nazwa, metoda_formula, metoda_factor, formula)
        VALUES (9103, 'sa', 'Substancja aktywna', 'obliczeniowy', 'SA', 1,
            NULL, NULL, NULL, NULL, 'sm - nacl - 0.6')
    """)
    db.execute("""
        INSERT INTO parametry_analityczne (id, kod, label, typ, skrot, precision,
            metoda_id, metoda_nazwa, metoda_formula, metoda_factor, formula)
        VALUES (9104, 'ph', 'pH', 'bezposredni', 'pH', 1, NULL, NULL, NULL, NULL, NULL)
    """)

    # etap — cykliczny
    db.execute("""
        INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu)
        VALUES (901, 'standaryzacja', 'Standaryzacja', 'cykliczny')
    """)

    # etap_parametry (catalog defaults)
    db.execute("""
        INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc,
            min_limit, max_limit, precision, spec_value, wymagany, grupa, formula, sa_bias)
        VALUES (901, 9101, 1, 44.0, 48.0, 1, 46.0, 1, 'lab', NULL, NULL)
    """)
    db.execute("""
        INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc,
            min_limit, max_limit, precision, spec_value, wymagany, grupa, formula, sa_bias)
        VALUES (901, 9102, 2, 0.5, 2.5, 2, NULL, 1, 'lab', NULL, NULL)
    """)
    db.execute("""
        INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc,
            min_limit, max_limit, precision, spec_value, wymagany, grupa, formula, sa_bias)
        VALUES (901, 9103, 3, 30.0, 40.0, 1, NULL, 1, 'lab', 'sm - nacl - 0.6', 0.6)
    """)
    db.execute("""
        INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc,
            min_limit, max_limit, precision, spec_value, wymagany, grupa, formula, sa_bias)
        VALUES (901, 9104, 4, 6.5, 7.5, 1, NULL, 0, 'lab', NULL, NULL)
    """)

    # etap_warunki (gate conditions)
    db.execute("""
        INSERT INTO etap_warunki (etap_id, parametr_id, operator, wartosc)
        VALUES (901, 9101, '>=', 44.0)
    """)

    # etap_korekty_katalog (correction substances for the stage)
    db.execute("""
        INSERT INTO etap_korekty_katalog (etap_id, substancja, jednostka, wykonawca, kolejnosc)
        VALUES (901, 'korekta_woda', 'kg', 'produkcja', 1)
    """)
    db.execute("""
        INSERT INTO etap_korekty_katalog (etap_id, substancja, jednostka, wykonawca, kolejnosc)
        VALUES (901, 'korekta_nacl', 'kg', 'produkcja', 2)
    """)

    # produkt_pipeline
    db.execute("""
        INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc)
        VALUES ('TestProd', 901, 1)
    """)

    # product-level limit overrides
    db.execute("""
        INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, min_limit, max_limit)
        VALUES ('TestProd', 901, 9101, 45.0, 47.0)
    """)
    db.execute("""
        INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, min_limit, max_limit)
        VALUES ('TestProd', 901, 9102, 5.8, 7.3)
    """)
    db.execute("""
        INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, min_limit, max_limit)
        VALUES ('TestProd', 901, 9103, 30.0, 42.0)
    """)
    db.execute("""
        INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, min_limit, max_limit)
        VALUES ('TestProd', 901, 9104, 4.0, 6.0)
    """)

    db.commit()


def _seed_jednorazowy(db):
    """Seed a jednorazowy 'utlenienie' stage with one parameter, no korekty."""
    db.execute("""
        INSERT INTO parametry_analityczne (id, kod, label, typ, skrot, precision)
        VALUES (9201, 'hl', 'Hydronadtlenek', 'bezposredni', 'HL', 1)
    """)
    db.execute("""
        INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu)
        VALUES (902, 'utlenienie', 'Utlenienie', 'jednorazowy')
    """)
    db.execute("""
        INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, min_limit, max_limit, precision)
        VALUES (902, 9201, 1, 0.5, 2.0, 1)
    """)
    db.execute("""
        INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc)
        VALUES ('TestProd2', 902, 1)
    """)
    db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_build_returns_etapy_and_parametry(db):
    """Result is not None and contains both required keys."""
    _seed(db)
    from mbr.pipeline.adapter import build_pipeline_context
    ctx = build_pipeline_context(db, "TestProd")
    assert ctx is not None
    assert "etapy_json" in ctx
    assert "parametry_lab" in ctx


def test_etapy_json_structure(db):
    """etapy_json entries have correct nazwa, sekcja_lab, read_only fields."""
    _seed(db)
    from mbr.pipeline.adapter import build_pipeline_context
    ctx = build_pipeline_context(db, "TestProd")
    etapy = ctx["etapy_json"]
    # at minimum one entry
    assert len(etapy) >= 1
    first = etapy[0]
    assert first["nazwa"] == "Standaryzacja"
    assert first["read_only"] is False
    assert "nr" in first
    # cykliczny => sekcja_lab must be "analiza"
    assert first["sekcja_lab"] == "analiza"


def test_parametry_lab_has_sekcja(db):
    """For cykliczny stage, parametry_lab key must be 'analiza' (not the stage kod)."""
    _seed(db)
    from mbr.pipeline.adapter import build_pipeline_context
    ctx = build_pipeline_context(db, "TestProd")
    plab = ctx["parametry_lab"]
    # should have 'analiza', not 'standaryzacja'
    assert "analiza" in plab
    assert "standaryzacja" not in plab


def test_parametry_lab_pole_format(db):
    """SM pole must have correct min/max/precision/measurement_type/target."""
    _seed(db)
    from mbr.pipeline.adapter import build_pipeline_context
    ctx = build_pipeline_context(db, "TestProd")
    pola = ctx["parametry_lab"]["analiza"]["pola"]
    sm = next((p for p in pola if p["kod"] == "sm"), None)
    assert sm is not None, "SM pole not found"
    # product-level limits override catalog defaults (45.0/47.0)
    assert sm["min"] == 45.0
    assert sm["max"] == 47.0
    assert sm["min_limit"] == 45.0
    assert sm["max_limit"] == 47.0
    assert sm["precision"] == 1
    assert sm["measurement_type"] == "bezp"
    assert sm["spec_value"] == 46.0
    assert sm["tag"] == "sm"
    assert sm["typ"] == "float"
    assert sm["grupa"] == "lab"


def test_titracja_has_calc_method(db):
    """NaCl (titracja) pole must have calc_method dict with factor."""
    _seed(db)
    from mbr.pipeline.adapter import build_pipeline_context
    ctx = build_pipeline_context(db, "TestProd")
    pola = ctx["parametry_lab"]["analiza"]["pola"]
    nacl = next((p for p in pola if p["kod"] == "nacl"), None)
    assert nacl is not None, "NaCl pole not found"
    assert nacl["measurement_type"] == "titracja"
    assert "calc_method" in nacl
    cm = nacl["calc_method"]
    assert cm["factor"] == 0.585
    assert "formula" in cm
    assert "name" in cm


def test_obliczeniowy_has_formula(db):
    """SA (obliczeniowy) pole must have formula field."""
    _seed(db)
    from mbr.pipeline.adapter import build_pipeline_context
    ctx = build_pipeline_context(db, "TestProd")
    pola = ctx["parametry_lab"]["analiza"]["pola"]
    sa = next((p for p in pola if p["kod"] == "sa"), None)
    assert sa is not None, "SA pole not found"
    assert sa["measurement_type"] == "obliczeniowy"
    assert "formula" in sa
    assert sa["formula"]  # must be non-empty


def test_empty_pipeline_returns_none(db):
    """If no pipeline exists for product, return None."""
    from mbr.pipeline.adapter import build_pipeline_context
    result = build_pipeline_context(db, "NoSuchProduct")
    assert result is None


def test_jednorazowy_no_dodatki(db):
    """Jednorazowy stage must NOT generate a companion 'dodatki' etap entry."""
    _seed_jednorazowy(db)
    from mbr.pipeline.adapter import build_pipeline_context
    ctx = build_pipeline_context(db, "TestProd2")
    assert ctx is not None
    sekcje = [e["sekcja_lab"] for e in ctx["etapy_json"]]
    assert "dodatki" not in sekcje
    # sekcja key should be the stage kod, not "analiza"
    plab = ctx["parametry_lab"]
    assert "utlenienie" in plab
    assert "analiza" not in plab


def test_adapter_output_compatible_with_save_wyniki(db):
    """pola_map[kod] must have min_limit and max_limit for save_wyniki compatibility."""
    _seed(db)
    from mbr.pipeline.adapter import build_pipeline_context
    ctx = build_pipeline_context(db, "TestProd")
    # build a pola_map the same way save_wyniki would
    pola_map = {}
    for sekcja_data in ctx["parametry_lab"].values():
        for pole in sekcja_data["pola"]:
            pola_map[pole["kod"]] = pole
    # Every pole must expose min_limit and max_limit (even if None)
    for kod, pole in pola_map.items():
        assert "min_limit" in pole, f"Missing min_limit on {kod}"
        assert "max_limit" in pole, f"Missing max_limit on {kod}"


# ---------------------------------------------------------------------------
# Helpers for dual-write tests
# ---------------------------------------------------------------------------

def _setup_pipeline(db):
    """Alias for _seed: full cykliczny pipeline for 'TestProd'."""
    _seed(db)


def _seed_params(db):
    """Seed only parametry_analityczne (no pipeline) — for no-pipeline test."""
    db.execute("""
        INSERT INTO parametry_analityczne (id, kod, label, typ, skrot, precision)
        VALUES (9901, 'sm', 'Sucha masa', 'bezposredni', 'SM', 1)
    """)
    db.commit()


# ---------------------------------------------------------------------------
# Task 5: pipeline_dual_write tests
# ---------------------------------------------------------------------------

from mbr.pipeline.models import create_sesja, get_pomiary


def test_dual_write_saves_to_ebr_pomiar(db):
    """When pipeline is active, save to ebr_pomiar alongside ebr_wyniki."""
    from mbr.pipeline.adapter import pipeline_dual_write

    _setup_pipeline(db)

    # Create MBR + EBR
    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia, parametry_lab, etapy_json) VALUES (1, 'TestProd', 1, '2026-01-01', '{}', '[]')")
    db.execute("INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start) VALUES (1, 1, 'T-1', '1/2026', '2026-01-01')")

    # Create pipeline session
    etap_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='standaryzacja'").fetchone()[0]
    sesja_id = create_sesja(db, 1, etap_id, runda=1, laborant="lab1")
    db.commit()

    # Dual write
    gate = pipeline_dual_write(db, ebr_id=1, sekcja="analiza__1",
                               values={"sm": 45.5, "nacl": 6.2}, wpisal="lab1")

    # Verify ebr_pomiar has data
    pomiary = get_pomiary(db, sesja_id)
    kods = {p["kod"] for p in pomiary}
    assert "sm" in kods
    assert "nacl" in kods

    # Verify gate result
    assert gate is not None
    assert "passed" in gate
    assert "sesja_id" in gate
    assert "etap_id" in gate


def test_dual_write_no_pipeline_returns_none(db):
    from mbr.pipeline.adapter import pipeline_dual_write
    _seed_params(db)

    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia, parametry_lab, etapy_json) VALUES (1, 'NoPipe', 1, '2026-01-01', '{}', '[]')")
    db.execute("INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start) VALUES (1, 1, 'T-1', '1/2026', '2026-01-01')")
    db.commit()

    gate = pipeline_dual_write(db, ebr_id=1, sekcja="analiza_koncowa",
                               values={"sm": 45.0}, wpisal="lab1")
    assert gate is None


def test_dual_write_dodatki_returns_none(db):
    """Dodatki section should not trigger gate evaluation."""
    from mbr.pipeline.adapter import pipeline_dual_write
    _setup_pipeline(db)

    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia, parametry_lab, etapy_json) VALUES (1, 'TestProd', 1, '2026-01-01', '{}', '[]')")
    db.execute("INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start) VALUES (1, 1, 'T-1', '1/2026', '2026-01-01')")
    db.commit()

    gate = pipeline_dual_write(db, ebr_id=1, sekcja="dodatki__1",
                               values={"korekta_woda": 50.0}, wpisal="lab1")
    assert gate is None
