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


# ---------------------------------------------------------------------------
# migrate_produkty tests
# ---------------------------------------------------------------------------

SAMPLE_CONFIG = {
    "products": {
        "Test_Prod": {
            "display_name": "Test Prod",
            "spec_number": "P100",
            "cas_number": "123-45-6",
            "expiry_months": 24,
            "opinion_pl": "Produkt OK",
            "opinion_en": "Product OK",
            "parameters": [],
            "variants": []
        },
        "Other_Prod": {
            "display_name": "Other Prod",
            "spec_number": "P200",
            "cas_number": "",
            "expiry_months": 6,
            "opinion_pl": "Dobry",
            "opinion_en": "Good",
            "parameters": [],
            "variants": []
        }
    }
}


def test_migrate_produkty(db):
    db.execute("INSERT INTO produkty (nazwa, kod) VALUES ('Test_Prod', 'TP')")
    db.commit()
    from scripts.migrate_produkty import migrate
    stats = migrate(db, SAMPLE_CONFIG)
    assert stats["updated"] >= 1
    row = db.execute("SELECT * FROM produkty WHERE nazwa='Test_Prod'").fetchone()
    assert row["display_name"] == "Test Prod"
    assert row["spec_number"] == "P100"
    assert row["cas_number"] == "123-45-6"
    assert row["expiry_months"] == 24
    assert row["opinion_pl"] == "Produkt OK"


def test_migrate_produkty_creates_missing(db):
    from scripts.migrate_produkty import migrate
    migrate(db, SAMPLE_CONFIG)
    row = db.execute("SELECT * FROM produkty WHERE nazwa='Other_Prod'").fetchone()
    assert row is not None
    assert row["spec_number"] == "P200"
    assert row["expiry_months"] == 6


def test_migrate_produkty_coalesce(db):
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('Test_Prod', 'Custom Name')")
    db.commit()
    from scripts.migrate_produkty import migrate
    migrate(db, SAMPLE_CONFIG)
    row = db.execute("SELECT display_name FROM produkty WHERE nazwa='Test_Prod'").fetchone()
    assert row["display_name"] == "Custom Name"


def test_migrate_produkty_idempotent(db):
    from scripts.migrate_produkty import migrate
    migrate(db, SAMPLE_CONFIG)
    migrate(db, SAMPLE_CONFIG)
    count = db.execute(
        "SELECT COUNT(*) as c FROM produkty WHERE nazwa IN ('Test_Prod', 'Other_Prod')"
    ).fetchone()["c"]
    assert count == 2


# ---------------------------------------------------------------------------
# API endpoint tests (produkty endpoints in parametry blueprint)
# ---------------------------------------------------------------------------

@pytest.fixture
def app_produkty(db):
    from flask import Flask
    from mbr.parametry import parametry_bp
    app = Flask(__name__)
    app.secret_key = "test"
    import mbr.parametry.routes as _routes
    _orig = _routes.db_session
    from contextlib import contextmanager
    @contextmanager
    def _test_db():
        yield db
    _routes.db_session = _test_db
    app.register_blueprint(parametry_bp)
    db.execute("INSERT INTO produkty (nazwa, kod, typy, display_name) VALUES ('Prod_A', 'PA', '[\"szarza\"]', 'Prod A')")
    db.execute("INSERT INTO produkty (nazwa, kod, typy, display_name, aktywny) VALUES ('Prod_B', 'PB', '[\"zbiornik\"]', 'Prod B', 0)")
    db.execute("INSERT INTO produkty (nazwa, kod, typy, display_name) VALUES ('Prod_C', 'PC', '[\"szarza\",\"zbiornik\"]', 'Prod C')")
    db.commit()
    yield app
    _routes.db_session = _orig

@pytest.fixture
def client_produkty(app_produkty):
    with app_produkty.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"login": "admin", "rola": "admin"}
        yield c

def test_get_produkty_active_only(client_produkty):
    resp = client_produkty.get("/api/produkty")
    data = resp.get_json()
    names = [p["nazwa"] for p in data]
    assert "Prod_A" in names
    assert "Prod_C" in names
    assert "Prod_B" not in names

def test_get_produkty_filter_typ(client_produkty):
    resp = client_produkty.get("/api/produkty?typ=zbiornik")
    data = resp.get_json()
    names = [p["nazwa"] for p in data]
    assert "Prod_C" in names
    assert "Prod_A" not in names

def test_update_produkty_new_fields(client_produkty, db):
    pid = db.execute("SELECT id FROM produkty WHERE nazwa='Prod_A'").fetchone()["id"]
    resp = client_produkty.put(f"/api/produkty/{pid}", json={
        "display_name": "Product Alpha",
        "spec_number": "P999",
        "expiry_months": 24,
    })
    assert resp.status_code == 200
    row = db.execute("SELECT * FROM produkty WHERE id=?", (pid,)).fetchone()
    assert row["display_name"] == "Product Alpha"
    assert row["spec_number"] == "P999"
    assert row["expiry_months"] == 24

def test_create_produkt(client_produkty, db):
    resp = client_produkty.post("/api/produkty", json={
        "nazwa": "New_Product",
        "display_name": "New Product",
        "kod": "NP",
        "typy": '["szarza","zbiornik"]',
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"]
    row = db.execute("SELECT * FROM produkty WHERE nazwa='New_Product'").fetchone()
    assert row["display_name"] == "New Product"
    assert row["typy"] == '["szarza","zbiornik"]'
