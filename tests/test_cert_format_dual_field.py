"""get_cert_params returns format_global + format_override (4-th dual-field pair after name_pl/name_en/method)."""
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
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ, precision) VALUES (1, 'nd20', 'nD20', 'bezposredni', 4)")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ, precision) VALUES (2, 'lk', 'LK', 'bezposredni', 2)")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('TEST', 'Test')")
    # Row 1: format NULL → inherit from registry precision (4)
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, format, variant_id) "
        "VALUES ('TEST', 1, 0, NULL, NULL)"
    )
    # Row 2: format override = "1" (different from registry precision = 2)
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, format, variant_id) "
        "VALUES ('TEST', 2, 1, '1', NULL)"
    )
    db.commit()


def test_get_cert_params_returns_format_dual_fields(db):
    _seed(db)
    rows = get_cert_params(db, "TEST")
    assert len(rows) == 2

    r0 = rows[0]
    assert r0["format_global"] == "4"  # registry precision as string
    assert r0["format_override"] is None
    assert r0["format"] == "4"  # legacy effective falls back to registry precision when NULL

    r1 = rows[1]
    assert r1["format_global"] == "2"
    assert r1["format_override"] == "1"
    assert r1["format"] == "1"  # override wins


def test_get_cert_variant_params_returns_format_dual_fields(db):
    _seed(db)
    db.execute("INSERT INTO cert_variants (id, produkt, variant_id, label, flags, kolejnosc) VALUES (10, 'TEST', 'lv', 'LV', '[]', 0)")
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, format, variant_id) "
        "VALUES ('TEST', 1, 0, '3', 10)"
    )
    db.commit()

    rows = get_cert_variant_params(db, 10)
    assert len(rows) == 1
    r = rows[0]
    assert r["format_global"] == "4"
    assert r["format_override"] == "3"
    assert r["format"] == "3"


def test_get_cert_params_format_global_empty_when_precision_null(db):
    """If registry precision is NULL, format_global should be '' (not 'None' string)."""
    db.execute("DELETE FROM parametry_analityczne")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ, precision) VALUES (1, 'x', 'X', 'bezposredni', NULL)")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('TEST', 'Test')")
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, format, variant_id) "
        "VALUES ('TEST', 1, 0, NULL, NULL)"
    )
    db.commit()

    rows = get_cert_params(db, "TEST")
    assert rows[0]["format_global"] == ""
    assert rows[0]["format_override"] is None
    assert rows[0]["format"] == "1"  # both override and registry NULL → final fallback "1"
