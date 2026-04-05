"""Tests for parametry_registry — centralized parameter queries."""

import sqlite3
import pytest
from mbr.models import init_mbr_tables
from mbr.seed_parametry import seed
from mbr.parametry_registry import (
    get_parametry_for_kontekst,
    get_etapy_config,
    get_calc_methods,
    build_parametry_lab,
)


@pytest.fixture
def db():
    """In-memory SQLite with seeded parametry tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    seed(conn)
    yield conn
    conn.close()


def test_amidowanie_defaults(db):
    params = get_parametry_for_kontekst(db, "Chegina_K7", "amidowanie")
    assert len(params) == 4
    kods = [p["kod"] for p in params]
    assert kods == ["le", "la", "lk", "nd20"]


def test_amidowanie_nawazka(db):
    params = get_parametry_for_kontekst(db, "Chegina_K7", "amidowanie")
    la = next(p for p in params if p["kod"] == "la")
    assert la["nawazka_g"] == 2.0
    assert la["metoda"]["factor"] == 5.61


def test_product_override(db):
    k7 = get_parametry_for_kontekst(db, "Chegina_K7", "czwartorzedowanie")
    glol = get_parametry_for_kontekst(db, "Chegina_K40GLOL", "czwartorzedowanie")
    k7_aa = next(p for p in k7 if p["kod"] == "aa")
    glol_aa = next(p for p in glol if p["kod"] == "aa")
    assert k7_aa["max"] == 0.50
    assert glol_aa["max"] == 0.30


def test_fallback_to_defaults(db):
    """Product not in bindings falls back to NULL produkt rows."""
    params = get_parametry_for_kontekst(db, "Chegina_K40GL", "amidowanie")
    assert len(params) == 4  # Falls back to NULL defaults


def test_empty_kontekst(db):
    params = get_parametry_for_kontekst(db, "Chegina_K7", "nonexistent")
    assert params == []


def test_calc_methods(db):
    methods = get_calc_methods(db)
    assert "nacl" in methods
    assert "so3" in methods
    assert methods["nacl"]["factor"] == 0.585
    assert methods["so3"]["method"] == "Jodometryczna"


def test_etapy_config_k7(db):
    cfg = get_etapy_config(db, "Chegina_K7")
    assert "amidowanie" in cfg
    assert "sulfonowanie" in cfg
    assert "utlenienie" in cfg
    assert "rozjasnianie" not in cfg
    assert cfg["amidowanie"]["korekty"] == ["DMAPA", "Wydłużenie czasu"]
    assert len(cfg["amidowanie"]["parametry"]) == 4


def test_etapy_config_glol(db):
    cfg = get_etapy_config(db, "Chegina_K40GLOL")
    assert "rozjasnianie" in cfg
    assert len(cfg) == 6


def test_etapy_config_simple_product(db):
    cfg = get_etapy_config(db, "Chelamid_DK")
    assert cfg == {}


def test_build_parametry_lab_k7(db):
    plab = build_parametry_lab(db, "Chegina_K7")
    assert "analiza" in plab
    assert "dodatki" in plab
    assert len(plab["analiza"]["pola"]) > 0
    sm = plab["analiza"]["pola"][0]
    assert sm["measurement_type"] in ("bezposredni", "titracja", "obliczeniowy")
    assert sm["typ"] == "float"


def test_build_parametry_lab_simple(db):
    plab = build_parametry_lab(db, "Chelamid_DK")
    assert "analiza_koncowa" in plab


def test_titracja_params_have_metoda(db):
    params = get_parametry_for_kontekst(db, "Chegina_K7", "sulfonowanie")
    so3 = next(p for p in params if p["kod"] == "so3")
    assert so3["typ"] == "titracja"
    assert so3["metoda"] is not None
    assert so3["metoda"]["factor"] == 0.4
    assert so3["nawazka_g"] == 10.0


def test_obliczeniowy_has_formula(db):
    params = get_parametry_for_kontekst(db, "Chegina_K7", "analiza_koncowa")
    sa = next((p for p in params if p["kod"] == "sa"), None)
    if sa:
        assert sa["typ"] == "obliczeniowy"
        assert sa["formula"] == "sm - nacl - 0.6"
