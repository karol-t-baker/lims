"""Migration script: NULL out parametry_cert overrides that equal registry value (after whitespace normalization)."""
import sqlite3
import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed(db):
    db.execute("DELETE FROM parametry_analityczne")
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, name_en, method_code) "
        "VALUES (1, 'nd20', 'Wsp. załamania', 'bezposredni', 'Refractive index', 'PN-EN ISO 5661')"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('A', 'A')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('B', 'B')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('C', 'C')")
    # A: exact match → all 3 fields nulled
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('A', 1, 0, 'Wsp. załamania', 'Refractive index', 'PN-EN ISO 5661', NULL)"
    )
    # B: trailing/inner whitespace → still matches after normalization
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('B', 1, 0, '  Wsp.   załamania  ', 'Refractive  index', '  PN-EN ISO 5661 ', NULL)"
    )
    # C: real override (different value) → preserved
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('C', 1, 0, 'Wsp. załamania n_{D}^{20}', 'Refr. idx (custom)', 'Internal proc 12', NULL)"
    )
    db.commit()


def test_migration_nulls_exact_match(db):
    _seed(db)
    from scripts.migrate_cert_override_cleanup import run_migration
    stats = run_migration(db)
    row = db.execute("SELECT name_pl, name_en, method FROM parametry_cert WHERE produkt='A'").fetchone()
    assert row["name_pl"] is None
    assert row["name_en"] is None
    assert row["method"] is None


def test_migration_nulls_after_whitespace_normalization(db):
    _seed(db)
    from scripts.migrate_cert_override_cleanup import run_migration
    stats = run_migration(db)
    row = db.execute("SELECT name_pl, name_en, method FROM parametry_cert WHERE produkt='B'").fetchone()
    assert row["name_pl"] is None
    assert row["name_en"] is None
    assert row["method"] is None


def test_migration_preserves_real_overrides(db):
    _seed(db)
    from scripts.migrate_cert_override_cleanup import run_migration
    stats = run_migration(db)
    row = db.execute("SELECT name_pl, name_en, method FROM parametry_cert WHERE produkt='C'").fetchone()
    assert row["name_pl"] == "Wsp. załamania n_{D}^{20}"
    assert row["name_en"] == "Refr. idx (custom)"
    assert row["method"] == "Internal proc 12"


def test_migration_returns_stats(db):
    _seed(db)
    from scripts.migrate_cert_override_cleanup import run_migration
    stats = run_migration(db)
    # 6 nullings: A×3 + B×3
    assert stats["nulled_total"] == 6
    assert stats["preserved_total"] == 3  # C×3
    assert stats["rows_processed"] == 3


def test_migration_idempotent(db):
    _seed(db)
    from scripts.migrate_cert_override_cleanup import run_migration
    stats1 = run_migration(db)
    stats2 = run_migration(db)
    # Second run nullifies nothing extra
    assert stats2["nulled_total"] == 0
    assert stats2["preserved_total"] == 3


def test_migration_handles_variant_rows(db):
    _seed(db)
    db.execute(
        "INSERT INTO cert_variants (id, produkt, variant_id, label, flags, kolejnosc) "
        "VALUES (10, 'A', 'lv', 'LV', '[]', 0)"
    )
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('A', 1, 0, 'Wsp. załamania', NULL, NULL, 10)"
    )
    db.commit()
    from scripts.migrate_cert_override_cleanup import run_migration
    stats = run_migration(db)
    row = db.execute("SELECT name_pl FROM parametry_cert WHERE variant_id=10").fetchone()
    assert row["name_pl"] is None  # variant override matched registry → NULL
    assert stats["rows_processed"] == 4  # 3 base + 1 variant


def test_migration_dry_run_does_not_modify_db(db):
    _seed(db)
    from scripts.migrate_cert_override_cleanup import run_migration
    stats = run_migration(db, dry_run=True)
    # Counts still computed
    assert stats["nulled_total"] == 6
    # But DB unchanged
    row = db.execute("SELECT name_pl FROM parametry_cert WHERE produkt='A'").fetchone()
    assert row["name_pl"] == "Wsp. załamania"  # NOT nulled


def test_migration_nulls_empty_string_when_registry_also_empty(db):
    """B6 regression cleanup: empty-string overrides where registry is also empty
    (or NULL) should be nulled — both effective values are equally blank."""
    _seed(db)
    db.execute(
        "UPDATE parametry_analityczne SET name_en='' WHERE id=1"
    )
    db.execute(
        "INSERT INTO produkty (nazwa, display_name) VALUES ('D', 'D')"
    )
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('D', 1, 1, NULL, '', NULL, NULL)"
    )
    db.commit()
    from scripts.migrate_cert_override_cleanup import run_migration
    run_migration(db)
    row = db.execute("SELECT name_en FROM parametry_cert WHERE produkt='D'").fetchone()
    assert row["name_en"] is None  # empty == empty after normalization → null
