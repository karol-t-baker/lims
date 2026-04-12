"""Tests for parameter centralization Phase 1."""
import sqlite3
import pytest


@pytest.fixture
def db():
    """In-memory DB with full schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from mbr.models import init_mbr_tables
    init_mbr_tables(conn)
    return conn


def test_parametry_etapy_has_cert_columns(db):
    """After init, parametry_etapy should have all cert columns."""
    cols = {r[1] for r in db.execute("PRAGMA table_info(parametry_etapy)").fetchall()}
    for col in ("cert_requirement", "cert_format", "cert_qualitative_result",
                "cert_kolejnosc", "on_cert", "cert_variant_id"):
        assert col in cols, f"Missing column: {col}"


def test_on_cert_defaults_to_zero(db):
    """New parametry_etapy rows should default on_cert=0."""
    db.execute("INSERT INTO parametry_analityczne (kod, label, typ) VALUES ('test', 'Test', 'bezposredni')")
    db.execute("INSERT INTO parametry_etapy (kontekst, parametr_id, produkt) VALUES ('analiza_koncowa', 1, 'TestProd')")
    row = db.execute("SELECT on_cert FROM parametry_etapy WHERE id=1").fetchone()
    assert row["on_cert"] == 0


# ---------------------------------------------------------------------------
# Migration tests (Task 2)
# ---------------------------------------------------------------------------

def _seed_cert_data(db):
    """Seed parametry_analityczne, parametry_etapy, parametry_cert, cert_variants for migration test."""
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (10, 'sm', 'Sucha masa', 'bezposredni')")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (20, 'nacl', 'Chlorek sodu', 'bezposredni')")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (30, 'odour', 'Zapach', 'binarny')")
    db.execute("INSERT INTO parametry_etapy (id, produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit) VALUES (1, 'Prod', 'analiza_koncowa', 10, 0, 35.0, NULL)")
    db.execute("INSERT INTO parametry_etapy (id, produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit) VALUES (2, 'Prod', 'analiza_koncowa', 20, 1, NULL, 5.5)")
    db.execute("INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, variant_id, name_pl, name_en, method) VALUES ('Prod', 10, 0, 'min 35,5', '1', NULL, 'Sucha masa', 'Dry matter', 'L903')")
    db.execute("INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, qualitative_result, variant_id) VALUES ('Prod', 30, 2, 'charakterystyczny', '1', 'zgodny/right', NULL)")
    db.execute("INSERT INTO cert_variants (id, produkt, variant_id, label, flags, remove_params, kolejnosc) VALUES (1, 'Prod', 'loreal', 'Loreal', '[]', '[]', 0)")
    db.execute("INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, variant_id, name_pl) VALUES ('Prod', 20, 0, 'max 5,5', '1', 1, 'NaCl extra')")
    db.commit()


def test_migration_copies_base_cert_params(db):
    _seed_cert_data(db)
    from scripts.migrate_cert_to_etapy import migrate
    migrate(db)
    row = db.execute("SELECT on_cert, cert_requirement, cert_format FROM parametry_etapy WHERE produkt='Prod' AND parametr_id=10 AND kontekst='analiza_koncowa'").fetchone()
    assert row["on_cert"] == 1
    assert row["cert_requirement"] == "min 35,5"
    assert row["cert_format"] == "1"


def test_migration_inserts_cert_only_params(db):
    _seed_cert_data(db)
    from scripts.migrate_cert_to_etapy import migrate
    migrate(db)
    row = db.execute("SELECT on_cert, cert_requirement, cert_qualitative_result FROM parametry_etapy WHERE produkt='Prod' AND parametr_id=30 AND kontekst='analiza_koncowa'").fetchone()
    assert row is not None
    assert row["on_cert"] == 1
    assert row["cert_qualitative_result"] == "zgodny/right"


def test_migration_handles_variant_add_params(db):
    _seed_cert_data(db)
    from scripts.migrate_cert_to_etapy import migrate
    migrate(db)
    row = db.execute("SELECT kontekst, cert_variant_id, cert_requirement, on_cert FROM parametry_etapy WHERE produkt='Prod' AND parametr_id=20 AND kontekst='cert_variant'").fetchone()
    assert row is not None
    assert row["cert_variant_id"] == 1
    assert row["cert_requirement"] == "max 5,5"
    assert row["on_cert"] == 1


def test_migration_is_idempotent(db):
    _seed_cert_data(db)
    from scripts.migrate_cert_to_etapy import migrate
    migrate(db)
    migrate(db)
    count = db.execute("SELECT COUNT(*) as c FROM parametry_etapy WHERE on_cert=1").fetchone()["c"]
    assert count == 3
