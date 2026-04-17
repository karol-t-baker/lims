"""Real-DB integration test: copy data/batch_db.sqlite, run migration,
verify the script is idempotent and non-destructive.

This test was originally a pre/post snapshot-identity check for Chelamid_DK,
but that assumption breaks once users edit the admin panel in the live DB
(flags can legitimately go to 0, bindings can be auto-deleted). The test
now only asserts that migrate() is a no-op on an already-migrated DB."""

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


def _counts(db):
    return {
        "parametry_etapy": db.execute(
            "SELECT COUNT(*) AS n FROM parametry_etapy"
        ).fetchone()["n"],
        "produkt_etap_limity": db.execute(
            "SELECT COUNT(*) AS n FROM produkt_etap_limity"
        ).fetchone()["n"],
        "parametry_cert": db.execute(
            "SELECT COUNT(*) AS n FROM parametry_cert"
        ).fetchone()["n"],
        "produkt_pipeline": db.execute(
            "SELECT COUNT(*) AS n FROM produkt_pipeline"
        ).fetchone()["n"],
    }


def test_migrate_is_noop_on_already_migrated_db(real_db_copy):
    """Once migrate() has run once, subsequent calls must not change row counts
    (the _migrations marker short-circuits the body)."""
    from scripts.migrate_parametry_ssot import migrate, already_applied

    if not already_applied(real_db_copy):
        pytest.skip("Real DB has not been migrated yet; this test asserts idempotence post-migration.")

    before = _counts(real_db_copy)
    migrate(real_db_copy)
    after = _counts(real_db_copy)
    assert after == before, f"migrate() changed counts on already-migrated DB. Before: {before}\nAfter: {after}"
