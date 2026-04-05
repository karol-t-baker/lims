"""Tests for mbr.registry.models."""

import json
import sqlite3
import pytest
from mbr.models import init_mbr_tables
from mbr.registry.models import (
    list_completed_products,
    list_completed_registry,
    get_registry_columns,
    export_wyniki_csv,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    # Migration: nr_zbiornika was added after initial schema
    try:
        conn.execute("ALTER TABLE ebr_batches ADD COLUMN nr_zbiornika TEXT")
        conn.commit()
    except Exception:
        pass
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_mbr(db, produkt, status="active", parametry_lab=None):
    if parametry_lab is None:
        parametry_lab = json.dumps({
            "analiza": {
                "pola": [
                    {"kod": "ph", "label": "pH", "min": 6.0, "max": 7.5},
                    {"kod": "aa", "label": "%AA", "min": 38.0, "max": 42.0},
                ]
            }
        })
    cur = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "dt_utworzenia) VALUES (?, 1, ?, '[]', ?, datetime('now'))",
        (produkt, status, parametry_lab),
    )
    db.commit()
    return cur.lastrowid


def _insert_ebr(db, mbr_id, batch_id, nr_partii, status="completed", typ="szarza"):
    cur = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, dt_end, status, typ) "
        "VALUES (?, ?, ?, datetime('now', '-1 hour'), datetime('now'), ?, ?)",
        (mbr_id, batch_id, nr_partii, status, typ),
    )
    db.commit()
    return cur.lastrowid


def _insert_wynik(db, ebr_id, sekcja, kod, tag, wartosc, w_limicie=1):
    db.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc, w_limicie, "
        "dt_wpisu, wpisal) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), 'tester')",
        (ebr_id, sekcja, kod, tag, wartosc, w_limicie),
    )
    db.commit()


@pytest.fixture
def seeded(db):
    """Two products, one completed batch each with wyniki."""
    mbr1 = _insert_mbr(db, "Chegina K40GL")
    mbr2 = _insert_mbr(db, "Chegina K7")
    ebr1 = _insert_ebr(db, mbr1, "B2026-001", "1/2026")
    ebr2 = _insert_ebr(db, mbr2, "B2026-002", "2/2026")
    _insert_wynik(db, ebr1, "analiza", "ph", "pH", 6.8)
    _insert_wynik(db, ebr1, "analiza", "aa", "%AA", 40.1)
    _insert_wynik(db, ebr2, "analiza", "ph", "pH", 6.5, w_limicie=0)
    return {"mbr1": mbr1, "mbr2": mbr2, "ebr1": ebr1, "ebr2": ebr2}


# ---------------------------------------------------------------------------
# list_completed_products
# ---------------------------------------------------------------------------

def test_list_completed_products_empty(db):
    assert list_completed_products(db) == []


def test_list_completed_products_returns_distinct(db, seeded):
    products = list_completed_products(db)
    assert "Chegina K40GL" in products
    assert "Chegina K7" in products
    assert len(products) == 2


def test_list_completed_products_excludes_open(db):
    mbr_id = _insert_mbr(db, "Chegina K40GLOL")
    _insert_ebr(db, mbr_id, "B2026-010", "10/2026", status="open")
    products = list_completed_products(db)
    assert "Chegina K40GLOL" not in products


def test_list_completed_products_ordered_alphabetically(db, seeded):
    products = list_completed_products(db)
    assert products == sorted(products)


# ---------------------------------------------------------------------------
# list_completed_registry
# ---------------------------------------------------------------------------

def test_list_completed_registry_empty(db):
    assert list_completed_registry(db) == []


def test_list_completed_registry_returns_all_completed(db, seeded):
    rows = list_completed_registry(db)
    assert len(rows) == 2


def test_list_completed_registry_wyniki_attached(db, seeded):
    rows = list_completed_registry(db)
    ebr1_row = next(r for r in rows if r["batch_id"] == "B2026-001")
    assert "ph" in ebr1_row["wyniki"]
    assert ebr1_row["wyniki"]["ph"]["wartosc"] == pytest.approx(6.8)


def test_list_completed_registry_filter_by_produkt(db, seeded):
    rows = list_completed_registry(db, produkt="Chegina K40GL")
    assert len(rows) == 1
    assert rows[0]["produkt"] == "Chegina K40GL"


def test_list_completed_registry_excludes_open(db, seeded):
    mbr_id = _insert_mbr(db, "Chegina K40GLOL")
    _insert_ebr(db, mbr_id, "B2026-099", "99/2026", status="open")
    rows = list_completed_registry(db)
    assert all(r["batch_id"] != "B2026-099" for r in rows)


def test_list_completed_registry_cert_count(db, seeded):
    # No certs inserted — cert_count should be 0
    rows = list_completed_registry(db)
    for r in rows:
        assert r["cert_count"] == 0


def test_list_completed_registry_filter_by_typ(db, seeded):
    # seeded already has mbr1 for "Chegina K40GL" wersja=1; use that mbr_id directly
    mbr_id = seeded["mbr1"]
    _insert_ebr(db, mbr_id, "B2026-Z1", "Z1/2026", typ="zbiornik")
    rows_szarza = list_completed_registry(db, produkt="Chegina K40GL", typ="szarza")
    rows_zbiornik = list_completed_registry(db, produkt="Chegina K40GL", typ="zbiornik")
    assert all(r["typ"] == "szarza" for r in rows_szarza)
    assert all(r["typ"] == "zbiornik" for r in rows_zbiornik)


# ---------------------------------------------------------------------------
# get_registry_columns
# ---------------------------------------------------------------------------

def test_get_registry_columns_no_active_mbr(db):
    assert get_registry_columns(db, "NonExistentProd") == []


def test_get_registry_columns_returns_pola(db, seeded):
    cols = get_registry_columns(db, "Chegina K40GL")
    assert isinstance(cols, list)
    assert len(cols) == 2
    kody = [c["kod"] for c in cols]
    assert "ph" in kody
    assert "aa" in kody


def test_get_registry_columns_legacy_analiza_koncowa(db):
    parametry = json.dumps({
        "analiza_koncowa": {
            "pola": [
                {"kod": "nd20", "label": "nd20", "min": 1.44, "max": 1.46},
            ]
        }
    })
    _insert_mbr(db, "LegacyProd", parametry_lab=parametry)
    cols = get_registry_columns(db, "LegacyProd")
    assert len(cols) == 1
    assert cols[0]["kod"] == "nd20"


def test_get_registry_columns_inactive_mbr_not_used(db):
    _insert_mbr(db, "DraftProd", status="draft")
    assert get_registry_columns(db, "DraftProd") == []


# ---------------------------------------------------------------------------
# export_wyniki_csv
# ---------------------------------------------------------------------------

def test_export_wyniki_csv_empty(db):
    rows = export_wyniki_csv(db)
    assert rows == []


def test_export_wyniki_csv_returns_rows(db, seeded):
    rows = export_wyniki_csv(db)
    assert len(rows) == 3  # 2 wyniki for ebr1, 1 for ebr2


def test_export_wyniki_csv_has_expected_keys(db, seeded):
    rows = export_wyniki_csv(db)
    required_keys = {"batch_id", "produkt", "nr_partii", "sekcja", "kod_parametru",
                     "tag", "wartosc", "w_limicie", "wpisal"}
    for row in rows:
        assert required_keys.issubset(row.keys())


def test_export_wyniki_csv_filter_by_produkt(db, seeded):
    rows = export_wyniki_csv(db, produkt="Chegina K40GL")
    assert all(r["produkt"] == "Chegina K40GL" for r in rows)
    assert len(rows) == 2


def test_export_wyniki_csv_excludes_open_batches(db, seeded):
    mbr_id = _insert_mbr(db, "Chegina K40GLOL")
    open_ebr = _insert_ebr(db, mbr_id, "B2026-OPEN", "50/2026", status="open")
    _insert_wynik(db, open_ebr, "analiza", "ph", "pH", 7.0)
    rows = export_wyniki_csv(db)
    assert all(r["batch_id"] != "B2026-OPEN" for r in rows)
