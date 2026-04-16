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


def test_alter_schema_adds_flag_columns(db):
    from scripts.migrate_parametry_ssot import alter_schema
    alter_schema(db)
    cols = {r["name"] for r in db.execute("PRAGMA table_info(produkt_etap_limity)").fetchall()}
    for expected in (
        "kolejnosc", "formula", "sa_bias", "krok", "wymagany", "grupa",
        "dla_szarzy", "dla_zbiornika", "dla_platkowania",
    ):
        assert expected in cols, f"missing column {expected}"


def test_alter_schema_idempotent(db):
    from scripts.migrate_parametry_ssot import alter_schema
    alter_schema(db)
    alter_schema(db)  # second call must not raise
    # Still valid schema
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (99, 'x', 'X', 'bezposredni')")
    db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (99, 'e', 'E', 'jednorazowy')")
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, dla_szarzy, dla_zbiornika, dla_platkowania) "
        "VALUES ('TEST', 99, 99, 1, 0, 0)"
    )
    row = db.execute("SELECT dla_szarzy, dla_zbiornika, dla_platkowania FROM produkt_etap_limity WHERE produkt='TEST'").fetchone()
    assert row["dla_szarzy"] == 1
    assert row["dla_zbiornika"] == 0


def test_ensure_pipeline_creates_entries_for_legacy_products(db):
    from scripts.migrate_parametry_ssot import ensure_pipeline_for_legacy
    _seed_minimal_catalog(db)
    # Legacy product with no pipeline row, parametry_etapy uses kontekst='analiza_koncowa'
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, kontekst, produkt, min_limit, max_limit) "
        "VALUES (1, 'analiza_koncowa', 'Chegina_K40GL', 0, 10)"
    )
    db.commit()
    ensure_pipeline_for_legacy(db)
    row = db.execute(
        "SELECT etap_id FROM produkt_pipeline WHERE produkt='Chegina_K40GL'"
    ).fetchone()
    assert row is not None
    assert row["etap_id"] == 6  # analiza_koncowa's etap_id from _seed_minimal_catalog


def test_ensure_pipeline_idempotent(db):
    from scripts.migrate_parametry_ssot import ensure_pipeline_for_legacy
    _seed_minimal_catalog(db)
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, kontekst, produkt, min_limit, max_limit) "
        "VALUES (1, 'analiza_koncowa', 'Chegina_K40GL', 0, 10)"
    )
    db.commit()
    ensure_pipeline_for_legacy(db)
    ensure_pipeline_for_legacy(db)  # must not duplicate
    n = db.execute(
        "SELECT COUNT(*) AS n FROM produkt_pipeline WHERE produkt='Chegina_K40GL'"
    ).fetchone()["n"]
    assert n == 1


def test_copy_limits_inserts_rows_with_default_typ_flags(db):
    from scripts.migrate_parametry_ssot import alter_schema, ensure_pipeline_for_legacy, copy_limits
    _seed_minimal_catalog(db)
    alter_schema(db)
    # Legacy row: Chelamid_DK has parametry_etapy row for 'dietanolamina'
    db.execute(
        "INSERT INTO parametry_etapy "
        "(parametr_id, kontekst, produkt, min_limit, max_limit, nawazka_g, precision, target, "
        " kolejnosc, formula, sa_bias, krok, grupa) "
        "VALUES (2, 'analiza_koncowa', 'Chelamid_DK', 80, 9999, 0.5, 1, NULL, 3, NULL, NULL, NULL, 'lab')"
    )
    # produkt_pipeline entry (or ensure_pipeline_for_legacy creates it)
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chelamid_DK', 6, 1)")
    db.commit()
    copy_limits(db)
    row = db.execute(
        "SELECT min_limit, max_limit, nawazka_g, precision, kolejnosc, grupa, "
        "dla_szarzy, dla_zbiornika, dla_platkowania "
        "FROM produkt_etap_limity WHERE produkt='Chelamid_DK' AND etap_id=6 AND parametr_id=2"
    ).fetchone()
    assert row is not None
    assert row["min_limit"] == 80
    assert row["max_limit"] == 9999
    assert row["nawazka_g"] == 0.5
    assert row["precision"] == 1
    assert row["kolejnosc"] == 3
    assert row["dla_szarzy"] == 1
    assert row["dla_zbiornika"] == 1
    assert row["dla_platkowania"] == 0


def test_copy_limits_preserves_existing_produkt_etap_limity_values(db):
    """If a pipeline product already has produkt_etap_limity rows, do not overwrite
    non-null values with NULLs from parametry_etapy."""
    from scripts.migrate_parametry_ssot import alter_schema, copy_limits
    _seed_minimal_catalog(db)
    alter_schema(db)
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chelamid_DK', 6, 1)")
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, min_limit, max_limit, precision) "
        "VALUES ('Chelamid_DK', 6, 2, 85, 99, 2)"  # already-set values
    )
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, kontekst, produkt, min_limit, max_limit, precision) "
        "VALUES (2, 'analiza_koncowa', 'Chelamid_DK', NULL, NULL, NULL)"
    )
    db.commit()
    copy_limits(db)
    row = db.execute(
        "SELECT min_limit, max_limit, precision FROM produkt_etap_limity "
        "WHERE produkt='Chelamid_DK' AND etap_id=6 AND parametr_id=2"
    ).fetchone()
    assert row["min_limit"] == 85
    assert row["max_limit"] == 99
    assert row["precision"] == 2


def test_copy_limits_skips_cert_variant_kontekst(db):
    """cert_variant rows are cert metadata, not pomiar bindings."""
    from scripts.migrate_parametry_ssot import alter_schema, copy_limits
    _seed_minimal_catalog(db)
    alter_schema(db)
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, kontekst, produkt) VALUES (1, 'cert_variant', 'Chelamid_DK')"
    )
    db.commit()
    copy_limits(db)
    n = db.execute("SELECT COUNT(*) AS n FROM produkt_etap_limity").fetchone()["n"]
    assert n == 0
