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
    assert len(params) == 5
    kods = [p["kod"] for p in params]
    assert kods == ["le", "la", "lk", "nd20", "barwa_I2"]


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
    assert len(params) == 5  # Falls back to NULL defaults


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
    """After MVP cleanup K7 has 3 etapy: sulfonowanie, utlenienie, standaryzacja.
    Pre-MVP also included amidowanie/namca/czwartorzedowanie."""
    cfg = get_etapy_config(db, "Chegina_K7")
    assert "sulfonowanie" in cfg
    assert "utlenienie" in cfg
    assert "standaryzacja" in cfg
    assert "amidowanie" not in cfg
    assert "rozjasnianie" not in cfg


def test_etapy_config_glol_empty_after_mvp(db):
    """After MVP cleanup only K7 retains process workflow; GLOL products
    have empty produkt_etapy → get_etapy_config returns {}."""
    cfg = get_etapy_config(db, "Chegina_K40GLOL")
    assert cfg == {}


def test_etapy_config_simple_product(db):
    cfg = get_etapy_config(db, "Chelamid_DK")
    assert cfg == {}


@pytest.mark.skip(reason="Superseded by test_pipeline_adapter.py — build_parametry_lab is now a thin wrapper over build_pipeline_context(typ=None). The adapter tests seed produkt_pipeline explicitly; here we'd need the same setup but the test adds no coverage beyond that.")
def test_build_parametry_lab_k7(db):
    pass


@pytest.mark.skip(reason="Superseded — see note on test_build_parametry_lab_k7.")
def test_build_parametry_lab_simple(db):
    pass


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


# ---------------------------------------------------------------------------
# Nadtlenki migration tests
# ---------------------------------------------------------------------------

def test_h2o2_skrot_renamed_to_perh(db):
    """After migration, h2o2 skrót must be '%Perh.' (not '%H₂O₂')."""
    row = db.execute(
        "SELECT skrot FROM parametry_analityczne WHERE kod='h2o2'"
    ).fetchone()
    assert row is not None, "h2o2 parameter must exist"
    assert row["skrot"] == "%Perh."


def test_nadtlenki_parameter_exists(db):
    """Migration must create a 'nadtlenki' parameter with correct fields."""
    row = db.execute(
        "SELECT kod, label, skrot, typ, jednostka "
        "FROM parametry_analityczne WHERE kod='nadtlenki'"
    ).fetchone()
    assert row is not None, "nadtlenki parameter must be created"
    assert row["label"] == "Nadtlenki"
    assert row["skrot"] == "%H\u2082O\u2082"
    assert row["typ"] == "titracja"
    assert row["jednostka"] == "%"

    # Verify method by name (resilient to ID shifts)
    metoda_row = db.execute(
        "SELECT m.nazwa FROM metody_miareczkowe m "
        "JOIN parametry_analityczne p ON p.metoda_id = m.id "
        "WHERE p.kod='nadtlenki'"
    ).fetchone()
    assert metoda_row is not None, "nadtlenki must be linked to a method"
    assert metoda_row["nazwa"] == "Nadtlenki [%]"


def test_nadtlenki_replaces_h2o2_in_analiza_koncowa(db):
    """For each of the 5 products, nadtlenki must be bound to analiza_koncowa
    and h2o2 must NOT be bound to analiza_koncowa."""
    products = [
        "Chegina_K40GLOL",
        "Cheminox_K",
        "Cheminox_K35",
        "Cheminox_LA",
        "Chemipol_ML",
    ]
    nadtlenki_id = db.execute(
        "SELECT id FROM parametry_analityczne WHERE kod='nadtlenki'"
    ).fetchone()
    assert nadtlenki_id is not None
    nadtlenki_id = nadtlenki_id["id"]

    h2o2_id = db.execute(
        "SELECT id FROM parametry_analityczne WHERE kod='h2o2'"
    ).fetchone()
    assert h2o2_id is not None
    h2o2_id = h2o2_id["id"]

    for prod in products:
        bound = db.execute(
            "SELECT id FROM parametry_etapy "
            "WHERE produkt=? AND kontekst='analiza_koncowa' AND parametr_id=?",
            (prod, nadtlenki_id),
        ).fetchone()
        assert bound is not None, f"{prod}: nadtlenki not bound to analiza_koncowa"

        old_bound = db.execute(
            "SELECT id FROM parametry_etapy "
            "WHERE produkt=? AND kontekst='analiza_koncowa' AND parametr_id=?",
            (prod, h2o2_id),
        ).fetchone()
        assert old_bound is None, f"{prod}: h2o2 still bound to analiza_koncowa"


# ---------------------------------------------------------------------------
# Precision cascade tests
# ---------------------------------------------------------------------------

def test_precision_cascade_global_default(db):
    """Without per-product override, precision comes from parametry_analityczne."""
    params = get_parametry_for_kontekst(db, "Chegina_K7", "analiza_koncowa")
    ph = next(p for p in params if p["kod"] == "ph_10proc")
    assert ph["precision"] == 2  # from parametry_analityczne seed


def test_precision_cascade_binding_override(db):
    """Per-product precision in parametry_etapy overrides global."""
    pa_id = db.execute(
        "SELECT id FROM parametry_analityczne WHERE kod='ph_10proc'"
    ).fetchone()[0]
    binding = db.execute(
        "SELECT id FROM parametry_etapy WHERE parametr_id=? AND kontekst='analiza_koncowa' AND produkt='Chegina_K7'",
        (pa_id,),
    ).fetchone()
    db.execute(
        "UPDATE parametry_etapy SET precision=4 WHERE id=?", (binding["id"],)
    )
    db.commit()
    params = get_parametry_for_kontekst(db, "Chegina_K7", "analiza_koncowa")
    ph = next(p for p in params if p["kod"] == "ph_10proc")
    assert ph["precision"] == 4


def test_precision_cascade_null_fallback(db):
    """When both are NULL, default to 2."""
    db.execute("UPDATE parametry_analityczne SET precision=NULL WHERE kod='ph_10proc'")
    db.commit()
    params = get_parametry_for_kontekst(db, "Chegina_K7", "analiza_koncowa")
    ph = next(p for p in params if p["kod"] == "ph_10proc")
    assert ph["precision"] == 2


@pytest.mark.skip(reason="Superseded — see note on test_build_parametry_lab_k7. Precision resolution is tested in test_pipeline_adapter.py / test_pipeline_models.py.")
def test_build_parametry_lab_uses_resolved_precision(db):
    pass
