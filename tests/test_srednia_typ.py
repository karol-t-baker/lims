"""Pipeline adapter support for typ='srednia' — a lightweight titracja-like mode
where a bezpośredni-style param is filled via a calc panel that takes 2 raw
numeric measurements and writes their arithmetic mean to the main field.

The samples persist via the same ebr_wyniki.samples_json path as titracja —
the only adapter-level concern is that the `typ` propagates as
`measurement_type='srednia'` so the laborant template can branch on it.
"""

import sqlite3
import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed_prod_with_srednia(db):
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, skrot, precision) "
        "VALUES (7701, 'sm', 'Sucha masa', 'srednia', 'SM', 1)"
    )
    db.execute(
        "INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
        "VALUES (770, 'analiza', 'Analiza', 'jednorazowy')"
    )
    db.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, "
        "min_limit, max_limit, precision, wymagany, grupa) "
        "VALUES (770, 7701, 1, 44.0, 48.0, 1, 1, 'lab')"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('TestProd', 'TestProd')")
    db.execute(
        "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) "
        "VALUES ('TestProd', 770, 1)"
    )
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
        "dla_szarzy, grupa) VALUES ('TestProd', 770, 7701, 1, 'lab')"
    )
    db.commit()


def test_srednia_maps_to_measurement_type_srednia(db):
    _seed_prod_with_srednia(db)
    from mbr.pipeline.adapter import build_pipeline_context
    ctx = build_pipeline_context(db, "TestProd")
    pola = ctx["parametry_lab"]["analiza"]["pola"]
    sm = next((p for p in pola if p["kod"] == "sm"), None)
    assert sm is not None
    # Critical: laborant JS branches on measurement_type === 'srednia'
    # to attach .ff.srednia class and route focus to openCalculatorSrednia.
    assert sm["measurement_type"] == "srednia"
    assert sm["typ_analityczny"] == "srednia"
    assert sm["typ"] == "float"  # numeric input in UI
    assert sm["precision"] == 1


def test_srednia_in_float_typy_set():
    """Ensure adapter guards (_FLOAT_TYPY) recognize 'srednia' as numeric."""
    from mbr.pipeline.adapter import _FLOAT_TYPY, _TYP_MAP
    assert "srednia" in _FLOAT_TYPY
    assert _TYP_MAP["srednia"] == "srednia"


def test_srednia_has_no_calc_method_or_formula(db):
    """Unlike titracja/obliczeniowy, srednia carries neither calc_method nor formula —
    the client computes the mean locally, the calc panel just holds the 2 raw inputs."""
    _seed_prod_with_srednia(db)
    from mbr.pipeline.adapter import build_pipeline_context
    ctx = build_pipeline_context(db, "TestProd")
    pola = ctx["parametry_lab"]["analiza"]["pola"]
    sm = next((p for p in pola if p["kod"] == "sm"), None)
    assert "calc_method" not in sm
    assert "formula" not in sm
