"""Tests for produkty table extensions."""
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

def test_produkty_has_new_columns(db):
    db.execute(
        "INSERT INTO produkty (nazwa, kod, display_name, spec_number, cas_number, "
        "expiry_months, opinion_pl, opinion_en) "
        "VALUES ('Test_Prod', 'TP', 'Test Prod', 'P100', '123-45-6', 24, 'OK', 'OK EN')"
    )
    row = db.execute("SELECT * FROM produkty WHERE nazwa='Test_Prod'").fetchone()
    assert row["display_name"] == "Test Prod"
    assert row["spec_number"] == "P100"
    assert row["cas_number"] == "123-45-6"
    assert row["expiry_months"] == 24
    assert row["opinion_pl"] == "OK"
    assert row["opinion_en"] == "OK EN"

def test_produkty_expiry_default(db):
    db.execute("INSERT INTO produkty (nazwa) VALUES ('Default_Prod')")
    row = db.execute("SELECT expiry_months FROM produkty WHERE nazwa='Default_Prod'").fetchone()
    assert row["expiry_months"] == 12

def test_produkty_auto_sync_from_mbr(db):
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "dt_utworzenia) VALUES ('NewProd_X', 1, 'active', '[]', '{}', datetime('now'))"
    )
    db.commit()
    init_mbr_tables(db)
    row = db.execute("SELECT * FROM produkty WHERE nazwa='NewProd_X'").fetchone()
    assert row is not None
    assert row["display_name"] == "NewProd X"
