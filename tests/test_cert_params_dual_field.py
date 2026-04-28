"""get_cert_params returns name_pl_global + name_pl_override etc."""
import sqlite3
import pytest

from mbr.models import init_mbr_tables
from mbr.parametry.registry import get_cert_params, get_cert_variant_params


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed(db):
    db.execute("DELETE FROM parametry_analityczne")
    # Global registry values
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, name_en, method_code) "
        "VALUES (1, 'nd20', 'Wsp. załamania', 'bezposredni', 'Refractive index', 'PN-EN ISO 5661')"
    )
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, name_en, method_code) "
        "VALUES (2, 'lk', 'Liczba kwasowa', 'bezposredni', 'Acid value', 'PN-EN ISO 660')"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('TEST', 'Test')")
    # Row 1: no overrides (NULL)
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('TEST', 1, 0, NULL, NULL, NULL, NULL)"
    )
    # Row 2: name_en overridden, method overridden, name_pl NULL
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('TEST', 2, 1, NULL, 'Acid number', 'Internal proc 12', NULL)"
    )
    db.commit()


def test_get_cert_params_returns_global_fields(db):
    _seed(db)
    rows = get_cert_params(db, "TEST")
    assert len(rows) == 2

    r0 = rows[0]
    # Global from parametry_analityczne
    assert r0["name_pl_global"] == "Wsp. załamania"
    assert r0["name_en_global"] == "Refractive index"
    assert r0["method_global"] == "PN-EN ISO 5661"
    # Override raw — all NULL
    assert r0["name_pl_override"] is None
    assert r0["name_en_override"] is None
    assert r0["method_override"] is None
    # Effective fallback (legacy field names) — kept for backward compat
    assert r0["name_pl"] == "Wsp. załamania"
    assert r0["name_en"] == "Refractive index"
    assert r0["method"] == "PN-EN ISO 5661"


def test_get_cert_params_returns_override_when_set(db):
    _seed(db)
    rows = get_cert_params(db, "TEST")
    r1 = rows[1]
    # Globals present
    assert r1["name_pl_global"] == "Liczba kwasowa"
    assert r1["name_en_global"] == "Acid value"
    assert r1["method_global"] == "PN-EN ISO 660"
    # Overrides — only name_en and method
    assert r1["name_pl_override"] is None
    assert r1["name_en_override"] == "Acid number"
    assert r1["method_override"] == "Internal proc 12"
    # Effective fallback prefers override
    assert r1["name_pl"] == "Liczba kwasowa"  # fallback to global
    assert r1["name_en"] == "Acid number"  # override
    assert r1["method"] == "Internal proc 12"  # override


def test_get_cert_variant_params_dual_fields(db):
    _seed(db)
    db.execute(
        "INSERT INTO cert_variants (id, produkt, variant_id, label, flags, kolejnosc) "
        "VALUES (10, 'TEST', 'lv', 'LV', '[]', 0)"
    )
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('TEST', 1, 0, 'Variant nazwa', NULL, NULL, 10)"
    )
    db.commit()

    rows = get_cert_variant_params(db, 10)
    assert len(rows) == 1
    r = rows[0]
    assert r["name_pl_global"] == "Wsp. załamania"
    assert r["name_pl_override"] == "Variant nazwa"
    assert r["name_en_global"] == "Refractive index"
    assert r["name_en_override"] is None
    assert r["name_pl"] == "Variant nazwa"  # effective


def test_get_cert_params_distinguishes_empty_override_from_null(db):
    """Empty-string override must round-trip as `""`, not fall back to global.

    The cert generator depends on this distinction: NULL = inherit registry,
    `""` = explicit blank (force empty cell on cert).
    """
    _seed(db)
    # Re-seed: clear and use parametr 1 only with empty-string name_en override
    db.execute("DELETE FROM parametry_cert")
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('TEST', 1, 0, NULL, '', NULL, NULL)"
    )
    db.commit()

    rows = get_cert_params(db, "TEST")
    assert len(rows) == 1
    r = rows[0]
    # Override is empty string, NOT None
    assert r["name_en_override"] == ""
    assert r["name_en_override"] is not None
    # Effective name_en respects the empty-string override (not the registry value)
    assert r["name_en"] == ""
    # Other fields fall back to global as expected
    assert r["name_pl"] == "Wsp. załamania"
    assert r["method"] == "PN-EN ISO 5661"
