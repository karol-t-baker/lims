"""Regression: backfill_cert_name_en.py must NOT overwrite empty-string name_en.

The cert editor uses the convention (see mbr/certs/routes.py around line 365):
  - parametry_cert.name_en = NULL → fall back to parametry_analityczne.name_en
  - parametry_cert.name_en = ''   → user explicitly hid the English name

Historical bug: backfill treated '' as a gap and re-filled it every deploy,
undoing the user's choice.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from mbr.models import init_mbr_tables
from scripts import backfill_cert_name_en as bfm
from scripts.backfill_cert_name_en import backfill


@pytest.fixture(autouse=True)
def _isolate_from_real_extraction_report(monkeypatch):
    """Point REPORT at a non-existent path so tests use only seeded cross-fill."""
    monkeypatch.setattr(bfm, "REPORT", Path("/nonexistent/cert_extraction_report.json"))


def _seed(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)

    conn.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('P1', 'P1')")
    conn.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('P2', 'P2')")

    # Shared analytical parameter "lk"
    pid = conn.execute(
        "INSERT INTO parametry_analityczne (kod, label, name_en, typ, grupa, precision) "
        "VALUES ('lk', 'Liczba kwasowa', 'Acid value', 'ilosciowy', 'lab', 2)"
    ).lastrowid

    # Donor product P1: has non-empty name_en (drives cross-fill)
    conn.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, "
        "format, name_pl, name_en, method, variant_id) "
        "VALUES ('P1', ?, 0, '', '2', 'Liczba kwasowa', 'Acid value', 'ISO 660', NULL)",
        (pid,),
    )
    # Target product P2 row A: NULL name_en — backfill SHOULD fill it
    rid_null = conn.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, "
        "format, name_pl, name_en, method, variant_id) "
        "VALUES ('P2', ?, 0, '', '2', 'Liczba kwasowa', NULL, NULL, NULL)",
        (pid,),
    ).lastrowid
    # Target product P2 row B: '' name_en — backfill MUST leave it as ''
    rid_empty = conn.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, "
        "format, name_pl, name_en, method, variant_id) "
        "VALUES ('P2', ?, 1, '', '2', 'Liczba kwasowa', '', '', NULL)",
        (pid,),
    ).lastrowid

    conn.commit()
    conn.close()
    return rid_null, rid_empty


def test_backfill_fills_null_but_preserves_empty_string(tmp_path):
    db_path = tmp_path / "batch.sqlite"
    rid_null, rid_empty = _seed(str(db_path))

    backfill(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row_null = conn.execute(
        "SELECT name_en, method FROM parametry_cert WHERE rowid = ?", (rid_null,)
    ).fetchone()
    row_empty = conn.execute(
        "SELECT name_en, method FROM parametry_cert WHERE rowid = ?", (rid_empty,)
    ).fetchone()
    conn.close()

    # NULL → filled from donor
    assert row_null["name_en"] == "Acid value", (
        f"NULL name_en should be backfilled, got: {row_null['name_en']!r}"
    )
    # Method must NOT be touched — this is a name_en backfill. Historically the
    # script also rewrote method, silently restoring overrides the user cleared.
    assert row_null["method"] is None, (
        f"method should be untouched (was NULL in seed), got: {row_null['method']!r}"
    )

    # '' → preserved (this is the regression check)
    assert row_empty["name_en"] == "", (
        f"Empty-string name_en is user intent 'no EN name' and must be preserved, "
        f"got: {row_empty['name_en']!r}"
    )


def test_backfill_is_idempotent_on_empty_string(tmp_path):
    """Running backfill twice must not progressively corrupt empty-string rows."""
    db_path = tmp_path / "batch.sqlite"
    _, rid_empty = _seed(str(db_path))

    backfill(db_path)
    backfill(db_path)

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT name_en FROM parametry_cert WHERE rowid = ?", (rid_empty,)
    ).fetchone()
    conn.close()

    assert row[0] == "", f"After 2 runs, empty-string name_en still expected, got: {row[0]!r}"
