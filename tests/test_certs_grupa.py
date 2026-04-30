"""Regression: cert generation includes grupa='zewn' params when on_cert=1 and value exists."""

import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


def _result_text(rt_or_str):
    """Extract text from a docxtpl RichText or plain string."""
    if rt_or_str is None or rt_or_str == "":
        return ""
    if hasattr(rt_or_str, "xml"):
        return rt_or_str.xml
    return str(rt_or_str)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed_zewn_cert(db, produkt="TEST_CERT_PROD"):
    """Seed a product with an external-lab (grupa='zewn') parameter on cert."""
    # Param with grupa='zewn'
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, skrot, precision, grupa) "
        "VALUES (200, 'tpc', 'Total plate count', 'bezposredni', 'TPC', 0, 'zewn')"
    )
    # produkty row so build_context doesn't fail
    db.execute(
        "INSERT INTO produkty (nazwa, display_name) VALUES (?, ?)",
        (produkt, "Test Cert Product"),
    )
    # cert_variants row
    cv_id = db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label) VALUES (?, 'base', 'Base')",
        (produkt,),
    ).lastrowid
    # parametry_cert so get_cert_params returns this param for the product
    db.execute(
        """INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format)
           VALUES (?, 200, 1, '<100 CFU/g', '1')""",
        (produkt,),
    )
    db.commit()
    return cv_id


def _make_client(monkeypatch, db):
    """Build a test context that monkeypatches db_session to use the in-memory db."""
    import mbr.db

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)


def test_build_context_renders_zewn_value(monkeypatch, db):
    """When a zewn param has a value, cert includes it in rows."""
    from mbr.certs.generator import build_context

    _make_client(monkeypatch, db)
    _seed_zewn_cert(db, produkt="TEST_CERT_PROD")

    # Simulated wyniki_flat as cert routes.py would pass — keyed by kod
    wyniki_flat = {"tpc": {"wartosc": 45.0}}

    ctx = build_context(
        produkt="TEST_CERT_PROD",
        variant_id="base",
        nr_partii="1/2026",
        dt_start="2026-04-19",
        wyniki_flat=wyniki_flat,
        extra_fields={},
        wystawil="tester",
    )

    # Context must contain a row whose result is '45' (format='1' → integer)
    rows = ctx.get("rows") or []
    tpc_rows = [r for r in rows if "Total plate count" in str(r.get("name_pl", ""))]
    assert tpc_rows, f"tpc row not found in cert rows, got: {[str(r.get('name_pl'))[:40] for r in rows]}"
    assert "45" in str(tpc_rows[0].get("result", "")), (
        f"tpc value missing from result: {tpc_rows[0].get('result')!r}"
    )


def test_build_context_empty_value_for_zewn_param(monkeypatch, db):
    """When the external-lab value hasn't been entered yet, cert renders an empty result row."""
    from mbr.certs.generator import build_context

    _make_client(monkeypatch, db)
    _seed_zewn_cert(db, produkt="TEST_CERT_PROD")

    ctx = build_context(
        produkt="TEST_CERT_PROD",
        variant_id="base",
        nr_partii="1/2026",
        dt_start="2026-04-19",
        wyniki_flat={},  # KJ hasn't entered anything yet
        extra_fields={},
        wystawil="tester",
    )
    rows = ctx.get("rows") or []
    tpc_rows = [r for r in rows if "Total plate count" in str(r.get("name_pl", ""))]
    assert tpc_rows, "tpc row must still appear on cert even without value"
    assert "−" in _result_text(tpc_rows[0].get("result")), (
        f"Expected '−' (U+2212) for empty zewn, got: {tpc_rows[0].get('result')!r}"
    )
