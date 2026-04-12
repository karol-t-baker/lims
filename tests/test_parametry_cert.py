"""Tests for parametry_cert table and parametry_analityczne extensions."""

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



def test_parametry_analityczne_has_name_en(db):
    """INSERT with name_en and method_code, verify they're readable."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, name_en, method_code) "
        "VALUES ('ph', 'pH', 'bezposredni', 'pH value', 'L928')"
    )
    db.commit()
    row = db.execute(
        "SELECT name_en, method_code FROM parametry_analityczne WHERE kod = 'ph'"
    ).fetchone()
    assert row is not None
    assert row["name_en"] == "pH value"
    assert row["method_code"] == "L928"


def test_parametry_cert_table_exists(db):
    """INSERT into parametry_cert, verify fields."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ) VALUES ('ph', 'pH', 'bezposredni')"
    )
    db.commit()
    param_id = db.execute(
        "SELECT id FROM parametry_analityczne WHERE kod = 'ph'"
    ).fetchone()["id"]

    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, qualitative_result) "
        "VALUES ('K40GLO', ?, 1, '6.5-7.5', '2', NULL)",
        (param_id,),
    )
    db.commit()
    row = db.execute(
        "SELECT produkt, parametr_id, kolejnosc, requirement, format, qualitative_result "
        "FROM parametry_cert WHERE produkt = 'K40GLO'"
    ).fetchone()
    assert row is not None
    assert row["produkt"] == "K40GLO"
    assert row["parametr_id"] == param_id
    assert row["kolejnosc"] == 1
    assert row["requirement"] == "6.5-7.5"
    assert row["format"] == "2"
    assert row["qualitative_result"] is None


def test_parametry_cert_unique_constraint(db):
    """Verify UNIQUE(produkt, parametr_id) constraint."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ) VALUES ('ph', 'pH', 'bezposredni')"
    )
    db.commit()
    param_id = db.execute(
        "SELECT id FROM parametry_analityczne WHERE kod = 'ph'"
    ).fetchone()["id"]

    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id) VALUES ('K40GLO', ?)",
        (param_id,),
    )
    db.commit()

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO parametry_cert (produkt, parametr_id) VALUES ('K40GLO', ?)",
            (param_id,),
        )
        db.commit()


def test_seed_has_name_en(db):
    """Verify seed populates name_en for key parameters."""
    from mbr.parametry.seed import seed
    seed(db)
    row = db.execute("SELECT name_en, method_code FROM parametry_analityczne WHERE kod='sm'").fetchone()
    assert row["name_en"] == "Dry matter [%]"
    assert row["method_code"] == "L903"


def test_seed_has_name_en_ph(db):
    from mbr.parametry.seed import seed
    seed(db)
    row = db.execute("SELECT name_en FROM parametry_analityczne WHERE kod='ph_10proc'").fetchone()
    assert row["name_en"] == "pH (20°C)"


def test_jakosciowy_typ_allowed(db):
    """INSERT with typ='jakosciowy', verify it works."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ) VALUES ('wyglad', 'Wygląd', 'jakosciowy')"
    )
    db.commit()
    row = db.execute(
        "SELECT typ FROM parametry_analityczne WHERE kod = 'wyglad'"
    ).fetchone()
    assert row is not None
    assert row["typ"] == "jakosciowy"
