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
