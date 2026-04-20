"""Regression: resolve_limity must fall back to parametry_analityczne.precision
when both produkt_etap_limity.precision and etap_parametry.precision are NULL.
Final default is 2 (matches legacy COALESCE(..., 2) semantics)."""

import sqlite3
import pytest

from mbr.models import init_mbr_tables
from mbr.pipeline.models import resolve_limity


def _seed(db, *, pa_precision, ep_precision, pel_precision):
    """Insert one parametr + etap + (maybe) product override, varying precision."""
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, skrot, precision) "
        "VALUES (999, 'ph_test', 'pH Test', 'bezposredni', 'pH', ?)",
        (pa_precision,),
    )
    db.execute(
        "INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
        "VALUES (666, 'analiza_koncowa_test', 'Analiza końcowa Test', 'jednorazowy')"
    )
    db.execute(
        "INSERT INTO etap_parametry (id, etap_id, parametr_id, kolejnosc, precision) "
        "VALUES (888, 666, 999, 1, ?)",
        (ep_precision,),
    )
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, precision, "
        "dla_szarzy, dla_zbiornika, dla_platkowania) "
        "VALUES ('TEST_P', 666, 999, ?, 1, 1, 0)",
        (pel_precision,),
    )
    db.commit()


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def test_precision_ovr_wins(db):
    """produkt_etap_limity.precision overrides all others."""
    _seed(db, pa_precision=2, ep_precision=4, pel_precision=3)
    [row] = resolve_limity(db, "TEST_P", 666)
    assert row["precision"] == 3


def test_precision_cat_fallback_when_ovr_null(db):
    """ovr NULL → etap_parametry.precision wins."""
    _seed(db, pa_precision=2, ep_precision=4, pel_precision=None)
    [row] = resolve_limity(db, "TEST_P", 666)
    assert row["precision"] == 4


def test_precision_global_fallback_when_ovr_and_cat_null(db):
    """ovr and cat both NULL → parametry_analityczne.precision wins. THE BUG FIX."""
    _seed(db, pa_precision=2, ep_precision=None, pel_precision=None)
    [row] = resolve_limity(db, "TEST_P", 666)
    assert row["precision"] == 2


def test_precision_default_2_when_all_null(db):
    """All three NULL → hardcoded default 2 (matches legacy COALESCE)."""
    _seed(db, pa_precision=None, ep_precision=None, pel_precision=None)
    [row] = resolve_limity(db, "TEST_P", 666)
    assert row["precision"] == 2


def test_precision_zero_override_wins(db):
    """Explicit override of 0 is valid (integer display); must NOT be mistaken for NULL."""
    _seed(db, pa_precision=2, ep_precision=4, pel_precision=0)
    [row] = resolve_limity(db, "TEST_P", 666)
    assert row["precision"] == 0
