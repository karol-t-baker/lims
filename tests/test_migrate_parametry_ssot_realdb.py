"""Real-DB integration test: copy data/batch_db.sqlite, run migration, assert
the post-migration shape for Chelamid_DK is identical (kod, limits, kolejność)
to what the pre-migration queries produced."""

import shutil
import sqlite3
from pathlib import Path

import pytest

REAL_DB = Path("data/batch_db.sqlite")


pytestmark = pytest.mark.skipif(
    not REAL_DB.exists(),
    reason="data/batch_db.sqlite not available in this environment",
)


@pytest.fixture
def real_db_copy(tmp_path):
    dst = tmp_path / "batch_db.sqlite"
    shutil.copy2(REAL_DB, dst)
    conn = sqlite3.connect(dst)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()


def _pre_migration_snapshot(db):
    """What Chelamid_DK 'should look like' pre-migration, via the pipeline path
    that the application currently uses for rendering."""
    return db.execute("""
        SELECT pa.kod, pel.min_limit, pel.max_limit, pel.nawazka_g, pel.precision
        FROM produkt_etap_limity pel
        JOIN parametry_analityczne pa ON pa.id = pel.parametr_id
        WHERE pel.produkt='Chelamid_DK' AND pel.etap_id=6
        ORDER BY pa.kod
    """).fetchall()


def _post_migration_snapshot(db):
    """Same query, but filtered to typ=szarza (should match pre-migration identity
    because default flag is dla_szarzy=1)."""
    return db.execute("""
        SELECT pa.kod, pel.min_limit, pel.max_limit, pel.nawazka_g, pel.precision
        FROM produkt_etap_limity pel
        JOIN parametry_analityczne pa ON pa.id = pel.parametr_id
        WHERE pel.produkt='Chelamid_DK' AND pel.etap_id=6 AND pel.dla_szarzy=1
        ORDER BY pa.kod
    """).fetchall()


def test_chelamid_dk_shape_unchanged_after_migration(real_db_copy):
    from scripts.migrate_parametry_ssot import migrate

    before = [dict(r) for r in _pre_migration_snapshot(real_db_copy)]
    migrate(real_db_copy)
    after = [dict(r) for r in _post_migration_snapshot(real_db_copy)]
    assert after == before, f"Chelamid_DK shape drifted.\nBefore: {before}\nAfter:  {after}"
