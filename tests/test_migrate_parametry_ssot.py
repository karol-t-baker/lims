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


def test_cleanup_legacy_orphans_removes_null_produkt(db):
    from scripts.migrate_parametry_ssot import cleanup_legacy_orphans
    _seed_minimal_catalog(db)
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, kontekst, produkt) VALUES (1, 'analiza_koncowa', NULL)"
    )
    db.commit()
    counts = cleanup_legacy_orphans(db)
    assert counts["null_produkt"] == 1
    remaining = db.execute("SELECT COUNT(*) AS n FROM parametry_etapy WHERE produkt IS NULL").fetchone()["n"]
    assert remaining == 0


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


def test_migrate_sa_bias_copies_global_to_per_product(db):
    from scripts.migrate_parametry_ssot import alter_schema, migrate_sa_bias
    _seed_minimal_catalog(db)
    alter_schema(db)
    # Parameter 1 has sa_bias set globally in etap_parametry for etap 6
    db.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, sa_bias) VALUES (6, 1, 0.25)"
    )
    # Two products both bound to parametr_id=1 via produkt_etap_limity
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('A', 6, 1)")
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('B', 6, 1)")
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id) VALUES ('A', 6, 1)"
    )
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id) VALUES ('B', 6, 1)"
    )
    db.commit()
    migrate_sa_bias(db)
    rows = db.execute(
        "SELECT produkt, sa_bias FROM produkt_etap_limity WHERE parametr_id=1 ORDER BY produkt"
    ).fetchall()
    assert [(r["produkt"], r["sa_bias"]) for r in rows] == [("A", 0.25), ("B", 0.25)]


def test_migrate_sa_bias_preserves_per_product_override(db):
    """If produkt_etap_limity.sa_bias is already set, do NOT overwrite with etap_parametry value."""
    from scripts.migrate_parametry_ssot import alter_schema, migrate_sa_bias
    _seed_minimal_catalog(db)
    alter_schema(db)
    db.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, sa_bias) VALUES (6, 1, 0.25)"
    )
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('A', 6, 1)")
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, sa_bias) VALUES ('A', 6, 1, 0.75)"
    )
    db.commit()
    migrate_sa_bias(db)
    row = db.execute(
        "SELECT sa_bias FROM produkt_etap_limity WHERE produkt='A' AND parametr_id=1"
    ).fetchone()
    assert row["sa_bias"] == 0.75


def test_migrate_cert_fields_inserts_into_parametry_cert(db):
    from scripts.migrate_parametry_ssot import migrate_cert_fields
    _seed_minimal_catalog(db)
    db.execute(
        "INSERT INTO parametry_etapy "
        "(parametr_id, kontekst, produkt, on_cert, cert_requirement, cert_format, "
        " cert_qualitative_result, cert_kolejnosc) "
        "VALUES (1, 'analiza_koncowa', 'Chelamid_DK', 1, 'max 11', '2', NULL, 3)"
    )
    db.commit()
    migrate_cert_fields(db)
    row = db.execute(
        "SELECT requirement, format, qualitative_result, kolejnosc, variant_id "
        "FROM parametry_cert WHERE produkt='Chelamid_DK' AND parametr_id=1"
    ).fetchone()
    assert row is not None
    assert row["requirement"] == "max 11"
    assert row["format"] == "2"
    assert row["qualitative_result"] is None
    assert row["kolejnosc"] == 3
    assert row["variant_id"] is None  # base cert (no variant)


def test_migrate_cert_fields_handles_variant(db):
    from scripts.migrate_parametry_ssot import migrate_cert_fields
    _seed_minimal_catalog(db)
    db.execute("INSERT INTO cert_variants (id, produkt, variant_id, label) VALUES (10, 'Chelamid_DK', 'pelna', 'Chelamid DK — PEŁNA')")
    db.execute(
        "INSERT INTO parametry_etapy "
        "(parametr_id, kontekst, produkt, on_cert, cert_requirement, cert_format, cert_variant_id, cert_kolejnosc) "
        "VALUES (2, 'cert_variant', 'Chelamid_DK', 1, '80-90', '1', 10, 5)"
    )
    db.commit()
    migrate_cert_fields(db)
    row = db.execute(
        "SELECT requirement, variant_id, kolejnosc FROM parametry_cert "
        "WHERE produkt='Chelamid_DK' AND parametr_id=2"
    ).fetchone()
    assert row["requirement"] == "80-90"
    assert row["variant_id"] == 10
    assert row["kolejnosc"] == 5


def test_migrate_cert_fields_skips_non_cert_rows(db):
    from scripts.migrate_parametry_ssot import migrate_cert_fields
    _seed_minimal_catalog(db)
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, kontekst, produkt, on_cert) "
        "VALUES (1, 'analiza_koncowa', 'Chelamid_DK', 0)"
    )
    db.commit()
    migrate_cert_fields(db)
    n = db.execute("SELECT COUNT(*) AS n FROM parametry_cert").fetchone()["n"]
    assert n == 0


def test_migrate_cert_fields_handles_base_and_variant_same_param(db):
    """Same (produkt, parametr_id) can have both base cert row (variant_id=NULL)
    AND variant cert row (variant_id=10) — 3-column UNIQUE allows this."""
    from scripts.migrate_parametry_ssot import migrate_cert_fields
    _seed_minimal_catalog(db)
    db.execute("INSERT INTO cert_variants (id, produkt, variant_id, label) "
               "VALUES (10, 'Chelamid_DK', 'pelna', 'Chelamid DK — PEŁNA')")
    # base cert for dietanolamina (DEA limits)
    db.execute(
        "INSERT INTO parametry_etapy "
        "(parametr_id, kontekst, produkt, on_cert, cert_requirement, cert_format) "
        "VALUES (2, 'analiza_koncowa', 'Chelamid_DK', 1, 'max 3', '2')"
    )
    # variant cert for dietanolamina (Dietanoloamid limits)
    db.execute(
        "INSERT INTO parametry_etapy "
        "(parametr_id, kontekst, produkt, on_cert, cert_requirement, cert_format, cert_variant_id) "
        "VALUES (2, 'cert_variant', 'Chelamid_DK', 1, '80-90', '1', 10)"
    )
    db.commit()
    migrate_cert_fields(db)
    rows = db.execute(
        "SELECT variant_id, requirement FROM parametry_cert "
        "WHERE produkt='Chelamid_DK' AND parametr_id=2 "
        "ORDER BY COALESCE(variant_id, 0)"
    ).fetchall()
    assert len(rows) == 2
    # First row: base (variant_id NULL), requirement 'max 3'
    assert rows[0]["variant_id"] is None
    assert rows[0]["requirement"] == "max 3"
    # Second row: variant 10, requirement '80-90'
    assert rows[1]["variant_id"] == 10
    assert rows[1]["requirement"] == "80-90"


def test_postflight_passes_on_healthy_migration(db):
    from scripts.migrate_parametry_ssot import alter_schema, postflight
    _seed_minimal_catalog(db)
    alter_schema(db)
    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, status, dt_utworzenia) VALUES (1, 'Chelamid_DK', 'active', '2026-04-16T00:00:00')")
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chelamid_DK', 6, 1)")
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, dla_szarzy) "
        "VALUES ('Chelamid_DK', 6, 1, 1)"
    )
    db.commit()
    assert postflight(db) == []


def test_postflight_fails_on_active_product_with_no_bindings(db):
    from scripts.migrate_parametry_ssot import alter_schema, postflight
    _seed_minimal_catalog(db)
    alter_schema(db)
    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, status, dt_utworzenia) VALUES (1, 'Chelamid_DK', 'active', '2026-04-16T00:00:00')")
    db.commit()
    errors = postflight(db)
    assert any("Chelamid_DK" in e and "no visible bindings" in e for e in errors)


def test_postflight_fails_on_orphan_binding(db):
    """produkt_etap_limity row for etap_id not in that produkt's pipeline."""
    from scripts.migrate_parametry_ssot import alter_schema, postflight
    _seed_minimal_catalog(db)
    alter_schema(db)
    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, status, dt_utworzenia) VALUES (1, 'Chelamid_DK', 'active', '2026-04-16T00:00:00')")
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chelamid_DK', 6, 1)")
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, dla_szarzy) "
        "VALUES ('Chelamid_DK', 7, 1, 1)"  # etap_id 7 NOT in pipeline for this produkt
    )
    db.commit()
    errors = postflight(db)
    assert any("orphan" in e.lower() for e in errors)


def test_full_migration_end_to_end_chelamid_dk_shape(db):
    """Seed DB in the legacy shape, run migrate(), verify the new SSOT shape."""
    from scripts.migrate_parametry_ssot import migrate, already_applied

    _seed_minimal_catalog(db)
    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, status, dt_utworzenia) VALUES (1, 'Chelamid_DK', 'active', '2026-04-16T00:00:00')")
    # Legacy-style bindings: parametry_etapy with limits + on_cert for dietanolamina
    db.execute(
        "INSERT INTO parametry_etapy "
        "(parametr_id, kontekst, produkt, min_limit, max_limit, nawazka_g, precision, "
        " kolejnosc, grupa, on_cert, cert_requirement, cert_format, cert_kolejnosc) "
        "VALUES (2, 'analiza_koncowa', 'Chelamid_DK', 80, 9999, 0.5, 1, 1, 'lab', "
        "        1, '80-90', '1', 5)"
    )
    db.execute(
        "INSERT INTO parametry_etapy "
        "(parametr_id, kontekst, produkt, min_limit, max_limit, precision, kolejnosc) "
        "VALUES (1, 'analiza_koncowa', 'Chelamid_DK', 0, 11, 2, 2)"
    )
    # Note: no produkt_pipeline row — migration will create it.
    db.commit()

    migrate(db)

    # Pipeline entry created
    pp = db.execute("SELECT etap_id FROM produkt_pipeline WHERE produkt='Chelamid_DK'").fetchall()
    assert len(pp) == 1
    assert pp[0]["etap_id"] == 6

    # Two produkt_etap_limity rows exist with default typ flags
    bindings = db.execute(
        "SELECT parametr_id, min_limit, max_limit, nawazka_g, precision, kolejnosc, "
        "       dla_szarzy, dla_zbiornika, dla_platkowania "
        "FROM produkt_etap_limity WHERE produkt='Chelamid_DK' ORDER BY kolejnosc"
    ).fetchall()
    assert len(bindings) == 2
    for b in bindings:
        assert b["dla_szarzy"] == 1
        assert b["dla_zbiornika"] == 1
        assert b["dla_platkowania"] == 0

    # Cert metadata migrated for dietanolamina
    cert = db.execute(
        "SELECT requirement, format, kolejnosc FROM parametry_cert "
        "WHERE produkt='Chelamid_DK' AND parametr_id=2"
    ).fetchone()
    assert cert["requirement"] == "80-90"
    assert cert["format"] == "1"
    assert cert["kolejnosc"] == 5

    # _migrations marker set
    assert already_applied(db) is True


def test_ensure_pipeline_covers_orphan_produkt_etap_limity(db):
    """Products with produkt_etap_limity rows but no produkt_pipeline get pipeline entries."""
    from scripts.migrate_parametry_ssot import alter_schema, ensure_pipeline_for_legacy
    _seed_minimal_catalog(db)
    alter_schema(db)
    # Chegina_K40GL has a produkt_etap_limity row but no produkt_pipeline entry
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id) "
        "VALUES ('Chegina_K40GL', 6, 1)"
    )
    db.commit()
    inserted = ensure_pipeline_for_legacy(db)
    assert ('Chegina_K40GL', 6) in inserted
    row = db.execute(
        "SELECT etap_id FROM produkt_pipeline WHERE produkt='Chegina_K40GL'"
    ).fetchone()
    assert row["etap_id"] == 6
