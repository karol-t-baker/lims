"""Cert flexibility — schema migrations + helpers + endpoints."""

import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


# ===========================================================================
# Task 1: schema migrations
# ===========================================================================

def test_schema_swiadectwa_has_recipient_name(db):
    cols = {r["name"] for r in db.execute("PRAGMA table_info(swiadectwa)").fetchall()}
    assert "recipient_name" in cols


def test_schema_swiadectwa_has_expiry_months_used(db):
    cols = {r["name"] for r in db.execute("PRAGMA table_info(swiadectwa)").fetchall()}
    assert "expiry_months_used" in cols


def test_schema_cert_variants_has_archived(db):
    cols = {r["name"] for r in db.execute("PRAGMA table_info(cert_variants)").fetchall()}
    assert "archived" in cols


def test_schema_cert_variants_archived_default_zero(db):
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label) VALUES (?, ?, ?)",
        ("TestProd", "base", "TestProd"),
    )
    db.commit()
    row = db.execute("SELECT archived FROM cert_variants WHERE produkt='TestProd'").fetchone()
    assert row["archived"] == 0
