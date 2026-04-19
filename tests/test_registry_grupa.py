"""Regression: completed-batches registry columns include grupa='zewn' params (no filter)."""

import sqlite3
import json
import pytest

from mbr.models import init_mbr_tables
from mbr.registry.models import get_registry_columns


def _seed_with_zewn_param(db):
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ, skrot, precision, grupa) "
               "VALUES (100, 'tpc', 'Total plate count', 'bezposredni', 'TPC', 0, 'zewn')")
    db.execute("INSERT OR IGNORE INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
               "VALUES (6, 'analiza_koncowa', 'Analiza końcowa', 'jednorazowy')")
    db.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (6, 100, 1)")
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('TEST_PROD', 6, 1)")
    db.execute("INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, grupa, dla_szarzy, dla_zbiornika, dla_platkowania) "
               "VALUES ('TEST_PROD', 6, 100, 'zewn', 1, 1, 0)")
    # Minimal MBR template so get_registry_columns has something to reference
    db.execute("INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, dt_utworzenia) "
               "VALUES ('TEST_PROD', 1, 'active', '[]', '{}', datetime('now'))")
    db.commit()


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    _seed_with_zewn_param(conn)
    yield conn
    conn.close()


def test_registry_columns_include_zewn_parametr(db):
    cols = get_registry_columns(db, "TEST_PROD")
    kods = [c["kod"] for c in cols if "kod" in c]
    assert "tpc" in kods, f"zewn param must appear in registry columns, got: {kods}"


def test_registry_column_has_grupa_metadata(db):
    cols = get_registry_columns(db, "TEST_PROD")
    tpc_col = next((c for c in cols if c.get("kod") == "tpc"), None)
    assert tpc_col is not None
    # Grupa metadata flows through if present in the column dict
    assert tpc_col.get("grupa") == "zewn" or "grupa" not in tpc_col, (
        "If grupa is exposed on columns, it must be 'zewn' (not filtered)"
    )
