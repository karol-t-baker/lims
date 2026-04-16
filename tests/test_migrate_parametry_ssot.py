"""Tests for scripts/migrate_parametry_ssot.py — consolidation of parameter bindings
into produkt_etap_limity with typ flags + cert metadata into parametry_cert."""

import sqlite3
import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    """In-memory SQLite with MBR schema initialized."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed_minimal_catalog(db):
    """Seed just enough parametry_analityczne + etapy_analityczne for migration tests.

    init_mbr_tables() seeds one row (id=1 nadtlenki) in parametry_analityczne; we
    delete it so tests can use id=1 without collision. etapy_analityczne is empty
    post-init so nothing to clear there.
    """
    db.execute("DELETE FROM parametry_analityczne")
    db.executemany(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision, aktywny) VALUES (?, ?, ?, ?, ?, 1)",
        [
            (1, "ph", "pH", "bezposredni", 2),
            (2, "dietanolamina", "%dietanolaminy", "titracja", 1),
            (3, "barwa_I2", "Barwa jodowa", "bezposredni", 0),
            (4, "gliceryny", "%gliceryny", "bezposredni", 2),
        ],
    )
    db.executemany(
        "INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (?, ?, ?, ?)",
        [
            (6, "analiza_koncowa", "Analiza końcowa", "jednorazowy"),
            (7, "dodatki", "Dodatki standaryzacyjne", "cykliczny"),
        ],
    )
    db.commit()


def test_migrate_script_importable():
    """Module should expose migrate() and main() callables."""
    from scripts import migrate_parametry_ssot as mod

    assert callable(mod.migrate)
    assert callable(mod.main)
    assert callable(mod.preflight)
    assert callable(mod.postflight)


def test_migrate_marks_as_applied(db):
    """Migration should mark itself as applied in _migrations."""
    from scripts.migrate_parametry_ssot import migrate, already_applied

    _seed_minimal_catalog(db)
    migrate(db)
    assert already_applied(db) is True


def test_migrate_skips_when_already_applied(db, capsys):
    """Second call to migrate() should skip and print message."""
    from scripts.migrate_parametry_ssot import migrate

    _seed_minimal_catalog(db)
    migrate(db)
    migrate(db)  # second call
    captured = capsys.readouterr()
    assert "already applied — skipping" in captured.out


def test_preflight_blocks_on_null_produkt(db):
    from scripts.migrate_parametry_ssot import preflight
    _seed_minimal_catalog(db)
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, kontekst, produkt) VALUES (1, 'analiza_koncowa', NULL)"
    )
    db.commit()
    blockers = preflight(db)
    assert any("NULL produkt" in b for b in blockers)


def test_preflight_passes_on_clean_db(db):
    from scripts.migrate_parametry_ssot import preflight
    _seed_minimal_catalog(db)
    assert preflight(db) == []


def test_preflight_reports_products_without_pipeline(db):
    from scripts.migrate_parametry_ssot import preflight
    _seed_minimal_catalog(db)
    # Chegina_K40GL has parametry_etapy rows but no produkt_pipeline row
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, kontekst, produkt, min_limit, max_limit) "
        "VALUES (1, 'analiza_koncowa', 'Chegina_K40GL', 0, 10)"
    )
    db.commit()
    blockers = preflight(db)
    # Legacy-only products are NOT blockers — script auto-creates pipeline entries.
    assert blockers == []
