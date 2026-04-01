"""test_migrate_v4_real.py — Run against actual data (skipped in CI)."""

import sqlite3
import pytest
from pathlib import Path

DB_PATH = Path("data/batch_db_v4.sqlite")

pytestmark = pytest.mark.skipif(not DB_PATH.exists(), reason="v4 DB not built yet")


@pytest.fixture
def db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def test_all_batches_have_events(db):
    """Every batch should have at least 1 event."""
    orphans = db.execute("""
        SELECT b.batch_id FROM batch b
        LEFT JOIN events e ON b.batch_id = e.batch_id
        WHERE e.id IS NULL
    """).fetchall()
    assert len(orphans) == 0, f"Batches without events: {[r[0] for r in orphans]}"


def test_all_batches_have_materials(db):
    """Every batch should have at least 1 material."""
    orphans = db.execute("""
        SELECT b.batch_id FROM batch b
        LEFT JOIN materials m ON b.batch_id = m.batch_id
        WHERE m.id IS NULL
    """).fetchall()
    assert len(orphans) == 0, f"Batches without materials: {[r[0] for r in orphans]}"


def test_no_null_timestamps(db):
    """Events should all have non-null dt."""
    nulls = db.execute("SELECT COUNT(*) FROM events WHERE dt IS NULL").fetchone()[0]
    assert nulls == 0


def test_event_types_valid(db):
    """All event_type values should be from the enum."""
    valid = {"dodatek", "analiza", "zmiana_stanu", "korekta"}
    types = db.execute("SELECT DISTINCT event_type FROM events").fetchall()
    actual = {r[0] for r in types}
    assert actual.issubset(valid), f"Invalid event types: {actual - valid}"


def test_stages_valid(db):
    """All stage values should be from the enum."""
    valid = {"amid", "smca", "czwart", "rozjasnianie", "sulfonowanie",
             "utlenienie", "standaryzacja"}
    stages = db.execute("SELECT DISTINCT stage FROM events").fetchall()
    actual = {r[0] for r in stages}
    assert actual.issubset(valid), f"Invalid stages: {actual - valid}"


def test_no_sentinel_values(db):
    """No -1 or -99 sentinel values in proznia_ba."""
    sentinels = db.execute("""
        SELECT COUNT(*) FROM events WHERE proznia_ba IN (-1, -99)
    """).fetchone()[0]
    assert sentinels == 0, f"{sentinels} sentinel values found in proznia_ba"


def test_analiza_koncowa_populated(db):
    """Most batches should have analiza_koncowa data."""
    total = db.execute("SELECT COUNT(*) FROM batch").fetchone()[0]
    with_ak = db.execute("""
        SELECT COUNT(*) FROM batch WHERE ak_ph_10proc IS NOT NULL
    """).fetchone()[0]
    assert with_ak / total > 0.7, f"Only {with_ak}/{total} batches have ak_ph_10proc"


def test_material_categories(db):
    """Materials should only be 'surowiec' or 'dodatek'."""
    valid = {"surowiec", "dodatek"}
    cats = db.execute("SELECT DISTINCT kategoria FROM materials").fetchall()
    actual = {r[0] for r in cats}
    assert actual.issubset(valid), f"Invalid categories: {actual - valid}"
