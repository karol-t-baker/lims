"""PR3-T4: cert build_context renders per-batch wartosc_text for jakosciowy; '−' for empty zewn."""

import json as _json
import sqlite3
from contextlib import contextmanager

import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed_cert_product(db, produkt="CP", kod="zapach", typ="jakosciowy", grupa="lab",
                       wartosci=None, cert_qr="charakterystyczny"):
    pid = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision, opisowe_wartosci) "
        "VALUES (?, ?, ?, ?, 0, ?)",
        (kod, kod.capitalize(), typ, grupa,
         _json.dumps(wartosci) if wartosci else None),
    ).lastrowid
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES (?, ?)", (produkt, produkt))
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label) VALUES (?, 'base', 'Base')",
        (produkt,),
    )
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, qualitative_result) "
        "VALUES (?, ?, 1, 'charakterystyczny', '1', ?)",
        (produkt, pid, cert_qr),
    )
    db.commit()
    return pid


def _patch_db(monkeypatch, db):
    import mbr.db
    import mbr.certs.generator

    @contextmanager
    def fake():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake)
    monkeypatch.setattr(mbr.certs.generator, "db_session", fake, raising=False)


def _find_row(ctx, kod):
    rows = ctx.get("rows", []) or []
    return next((r for r in rows if r.get("kod") == kod), None)


def test_build_context_uses_wartosc_text_for_jakosciowy(monkeypatch, db):
    from mbr.certs.generator import build_context
    _seed_cert_product(db, wartosci=["charakterystyczny", "obcy"], cert_qr="charakterystyczny")
    _patch_db(monkeypatch, db)
    wyniki_flat = {"zapach": {"wartosc": None, "wartosc_text": "obcy"}}
    ctx = build_context("CP", "base", "1/2026", "2026-04-20", wyniki_flat, {}, "wystawil")
    row = _find_row(ctx, "zapach")
    assert row is not None
    assert row["result"] == "obcy"


def test_build_context_falls_back_to_qualitative_result_when_wartosc_text_empty(monkeypatch, db):
    from mbr.certs.generator import build_context
    _seed_cert_product(db, wartosci=["charakterystyczny"], cert_qr="charakterystyczny")
    _patch_db(monkeypatch, db)
    wyniki_flat = {}
    ctx = build_context("CP", "base", "1/2026", "2026-04-20", wyniki_flat, {}, "wystawil")
    row = _find_row(ctx, "zapach")
    assert row is not None
    assert row["result"] == "charakterystyczny"


def test_build_context_renders_minus_for_empty_zewn(monkeypatch, db):
    from mbr.certs.generator import build_context
    _seed_cert_product(db, kod="siarka", typ="bezposredni", grupa="zewn", cert_qr=None)
    _patch_db(monkeypatch, db)
    wyniki_flat = {}
    ctx = build_context("CP", "base", "1/2026", "2026-04-20", wyniki_flat, {}, "wystawil")
    row = _find_row(ctx, "siarka")
    assert row is not None
    assert row["result"] == "\u2212"


def test_build_context_lab_numeric_unchanged(monkeypatch, db):
    """Regression: existing lab numeric rendering still works."""
    from mbr.certs.generator import build_context
    _seed_cert_product(db, kod="gestosc", typ="bezposredni", grupa="lab", cert_qr=None)
    _patch_db(monkeypatch, db)
    wyniki_flat = {"gestosc": {"wartosc": 1.0234}}
    ctx = build_context("CP", "base", "1/2026", "2026-04-20", wyniki_flat, {}, "wystawil")
    row = _find_row(ctx, "gestosc")
    assert row is not None
    assert row["result"] not in ("", "\u2212")
