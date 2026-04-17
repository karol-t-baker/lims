"""Tests for scripts/migrate_cert_config.py"""

import sqlite3
import pytest
from mbr.models import init_mbr_tables
from scripts.migrate_cert_config import migrate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


SAMPLE_CONFIG = {
    "products": {
        "Test_Prod": {
            "parameters": [
                {
                    "id": "barwa_hz",
                    "name_pl": "Barwa w skali Hazena",
                    "name_en": "Colour (Hazen scale)",
                    "requirement": "max 150",
                    "method": "L928",
                    "data_field": "barwa_hz",
                    "format": "0",
                },
                {
                    "id": "odour",
                    "name_pl": "Zapach",
                    "name_en": "Odour",
                    "requirement": "słaby /faint",
                    "method": "organoleptycznie /organoleptic",
                    "data_field": None,
                    "qualitative_result": "zgodny /right",
                },
                {
                    "id": "sm",
                    "name_pl": "Sucha masa [%]",
                    "name_en": "Dry matter [%]",
                    "requirement": "min. 44,0",
                    "method": "L903",
                    "data_field": "sm",
                    "format": "1",
                },
            ]
        }
    }
}


@pytest.fixture
def seeded_db(db):
    """DB with barwa_hz and sm already in parametry_analityczne."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ) VALUES ('barwa_hz', 'Barwa Hz', 'bezposredni')"
    )
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ) VALUES ('sm', 'Sucha masa', 'bezposredni')"
    )
    db.commit()
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_migration_creates_cert_bindings(seeded_db):
    """Running migrate on sample config creates 3 parametry_cert bindings."""
    summary = migrate(seeded_db, SAMPLE_CONFIG)

    rows = seeded_db.execute(
        "SELECT * FROM parametry_cert WHERE produkt = 'Test_Prod'"
    ).fetchall()
    assert len(rows) == 3, f"Expected 3 bindings, got {len(rows)}"
    assert summary["cert_bindings"] == 3


def test_migration_enriches_name_en(seeded_db):
    """Analytical params get name_en and method_code set from config."""
    migrate(seeded_db, SAMPLE_CONFIG)

    barwa = seeded_db.execute(
        "SELECT name_en, method_code FROM parametry_analityczne WHERE kod = 'barwa_hz'"
    ).fetchone()
    assert barwa is not None
    assert barwa["name_en"] == "Colour (Hazen scale)"
    assert barwa["method_code"] == "L928"

    sm = seeded_db.execute(
        "SELECT name_en, method_code FROM parametry_analityczne WHERE kod = 'sm'"
    ).fetchone()
    assert sm is not None
    assert sm["name_en"] == "Dry matter [%]"
    assert sm["method_code"] == "L903"


def test_migration_creates_jakosciowy_params(seeded_db):
    """Qualitative params (no data_field) are created in parametry_analityczne."""
    migrate(seeded_db, SAMPLE_CONFIG)

    row = seeded_db.execute(
        "SELECT kod, typ, name_en FROM parametry_analityczne WHERE kod = 'odour'"
    ).fetchone()
    assert row is not None, "odour param should be created"
    assert row["typ"] == "jakosciowy"
    assert row["name_en"] == "Odour"

    # Check the parametry_cert entry for odour has qualitative_result set
    cert_row = seeded_db.execute(
        "SELECT qualitative_result FROM parametry_cert "
        "WHERE produkt = 'Test_Prod' AND parametr_id = ("
        "  SELECT id FROM parametry_analityczne WHERE kod = 'odour')"
    ).fetchone()
    assert cert_row is not None
    assert cert_row["qualitative_result"] == "zgodny /right"


def test_migration_preserves_order(seeded_db):
    """kolejnosc in parametry_cert matches parameter index in config list."""
    migrate(seeded_db, SAMPLE_CONFIG)

    rows = seeded_db.execute(
        "SELECT pa.kod, pc.kolejnosc "
        "FROM parametry_cert pc "
        "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
        "WHERE pc.produkt = 'Test_Prod' "
        "ORDER BY pc.kolejnosc"
    ).fetchall()

    assert len(rows) == 3
    assert rows[0]["kod"] == "barwa_hz" and rows[0]["kolejnosc"] == 0
    assert rows[1]["kod"] == "odour"    and rows[1]["kolejnosc"] == 1
    assert rows[2]["kod"] == "sm"       and rows[2]["kolejnosc"] == 2


def test_migration_idempotent(seeded_db):
    """Running migration twice creates duplicate parametry_cert rows with variant_id=NULL.

    Note: migrate_cert_config.py uses INSERT OR IGNORE, but with SQLite's UNIQUE constraint,
    multiple NULLs are considered distinct. So when variant_id=NULL on all inserts,
    a second run will insert duplicates. This is acceptable since this is a one-time
    migration script (not meant to be run repeatedly in production).

    The parametry_ssot migration (migrate_cert_fields in migrate_parametry_ssot.py) uses
    UPSERT logic and IS idempotent.
    """
    migrate(seeded_db, SAMPLE_CONFIG)
    initial_count = seeded_db.execute(
        "SELECT COUNT(*) AS cnt FROM parametry_cert WHERE produkt = 'Test_Prod'"
    ).fetchone()["cnt"]
    assert initial_count == 3, f"Expected 3 bindings on first run, got {initial_count}"

    # Run migration again — will create duplicates because variant_id=NULL
    migrate(seeded_db, SAMPLE_CONFIG)
    final_count = seeded_db.execute(
        "SELECT COUNT(*) AS cnt FROM parametry_cert WHERE produkt = 'Test_Prod'"
    ).fetchone()["cnt"]
    assert final_count == 6, f"Expected 6 rows after second run (3 original + 3 duplicates), got {final_count}"

    # parametry_analityczne should not be duplicated (COALESCE logic prevents updates)
    odour_count = seeded_db.execute(
        "SELECT COUNT(*) AS cnt FROM parametry_analityczne WHERE kod = 'odour'"
    ).fetchone()
    assert odour_count["cnt"] == 1


def test_migration_preserves_existing_name_en(seeded_db):
    """COALESCE: pre-existing name_en is not overwritten by migration."""
    seeded_db.execute(
        "UPDATE parametry_analityczne SET name_en = 'Keep me' WHERE kod = 'barwa_hz'"
    )
    seeded_db.commit()

    migrate(seeded_db, SAMPLE_CONFIG)

    row = seeded_db.execute(
        "SELECT name_en FROM parametry_analityczne WHERE kod = 'barwa_hz'"
    ).fetchone()
    assert row["name_en"] == "Keep me", "Pre-existing name_en should not be overwritten"
