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


# ===========================================================================
# Task 3: _sanitize_filename_segment
# ===========================================================================

def test_sanitize_passes_normal_text():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("ADAM&PARTNER") == "ADAM&PARTNER"


def test_sanitize_strips_path_separators():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("ADAM/PARTNER") == "ADAMPARTNER"
    assert _sanitize_filename_segment("ADAM\\PARTNER") == "ADAMPARTNER"
    assert _sanitize_filename_segment("ADAM:PARTNER") == "ADAMPARTNER"


def test_sanitize_strips_control_chars():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("ADAM\x00\x01PARTNER") == "ADAMPARTNER"


def test_sanitize_trims_whitespace():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("  ADAM  ") == "ADAM"


def test_sanitize_max_40_chars():
    from mbr.certs.generator import _sanitize_filename_segment
    long_name = "A" * 100
    assert _sanitize_filename_segment(long_name) == "A" * 40


def test_sanitize_empty_returns_empty():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("") == ""
    assert _sanitize_filename_segment("   ") == ""
    assert _sanitize_filename_segment(None) == ""


def test_sanitize_keeps_polish_chars_and_ampersand():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("Łódź & Co.") == "Łódź & Co."


# ===========================================================================
# Task 4: _cert_names with recipient + has_order_number
# ===========================================================================

def test_cert_names_baseline_unchanged():
    """Old signature still works (legacy callers)."""
    from mbr.certs.generator import _cert_names
    folder, pdf, nr = _cert_names("Chegina_K7", "Chegina K7", "4/2026")
    assert folder == "Chegina K7"
    assert pdf == "Chegina K7 4.pdf"
    assert nr == "4"


def test_cert_names_with_recipient():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7", "4/2026",
                            recipient_name="ADAM&PARTNER")
    assert pdf == "Chegina K7 — ADAM&PARTNER 4.pdf"


def test_cert_names_with_recipient_and_mb_variant():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7 — MB", "4/2026",
                            recipient_name="ADAM&PARTNER")
    assert pdf == "Chegina K7 MB — ADAM&PARTNER 4.pdf"


def test_cert_names_recipient_with_slash_sanitized():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7", "4/2026",
                            recipient_name="ADAM/Partner")
    assert pdf == "Chegina K7 — ADAMPartner 4.pdf"


def test_cert_names_empty_recipient_omitted():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7", "4/2026", recipient_name="   ")
    assert pdf == "Chegina K7 4.pdf"


def test_cert_names_with_order_number_suffix():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7", "4/2026",
                            has_order_number=True)
    assert pdf == "Chegina K7 4 (NRZAM).pdf"


def test_cert_names_with_recipient_and_order_number():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7", "4/2026",
                            recipient_name="ADAM", has_order_number=True)
    assert pdf == "Chegina K7 — ADAM 4 (NRZAM).pdf"
