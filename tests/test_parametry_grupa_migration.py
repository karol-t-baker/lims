"""Regression: parametry_analityczne.grupa column added idempotently by init_mbr_tables."""

import sqlite3
import pytest

from mbr.models import init_mbr_tables


def _cols(db, table):
    return {r[1]: r for r in db.execute(f"PRAGMA table_info({table})").fetchall()}


def test_init_adds_grupa_column():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_mbr_tables(db)
    cols = _cols(db, "parametry_analityczne")
    assert "grupa" in cols, "grupa column must exist after init"
    # PRAGMA table_info columns: (cid, name, type, notnull, dflt_value, pk)
    assert cols["grupa"][2].upper() == "TEXT"
    assert cols["grupa"][4] == "'lab'", f"default must be 'lab', got {cols['grupa'][4]!r}"


def test_init_is_idempotent_on_grupa():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_mbr_tables(db)
    # Second call must not raise even though column already exists
    init_mbr_tables(db)
    cols = _cols(db, "parametry_analityczne")
    # Still exactly one 'grupa' column
    names = [r[1] for r in db.execute("PRAGMA table_info(parametry_analityczne)").fetchall()]
    assert names.count("grupa") == 1


def test_existing_rows_get_default_grupa():
    """Rows inserted BEFORE the migration ran should get 'lab' as grupa."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    # Seed parametry_analityczne WITHOUT grupa column (simulate pre-migration state)
    db.executescript("""
        CREATE TABLE parametry_analityczne (
            id INTEGER PRIMARY KEY, kod TEXT UNIQUE, label TEXT, typ TEXT,
            skrot TEXT, precision INTEGER, jednostka TEXT,
            metoda_nazwa TEXT, formula TEXT, aktywny INTEGER DEFAULT 1,
            metoda_formula TEXT, metoda_factor REAL, metoda_id INTEGER,
            name_en TEXT, method_code TEXT
        );
        INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (1, 'ph', 'pH', 'bezposredni');
    """)
    db.commit()

    # Now run the migration
    init_mbr_tables(db)

    row = db.execute("SELECT grupa FROM parametry_analityczne WHERE id=1").fetchone()
    assert row["grupa"] == "lab"
