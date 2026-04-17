"""Real-DB integration test: run MVP cleanup on a copy of data/batch_db.sqlite
and assert key invariants. Skips cleanly when DB file is missing."""

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


def test_migrate_on_real_db_produces_k7_4_pipeline_stages(real_db_copy):
    from scripts.mvp_pipeline_cleanup import migrate

    migrate(real_db_copy)

    # K7 pipeline: 4 rows (sulfon, utlen, standard, analiza_koncowa)
    rows = real_db_copy.execute(
        "SELECT ea.kod FROM produkt_pipeline pp "
        "JOIN etapy_analityczne ea ON pp.etap_id=ea.id "
        "WHERE pp.produkt='Chegina_K7' ORDER BY pp.kolejnosc"
    ).fetchall()
    kody = [r["kod"] for r in rows]
    assert kody == ["sulfonowanie", "utlenienie", "standaryzacja", "analiza_koncowa"]


def test_migrate_on_real_db_reduces_non_k7_to_single_stage(real_db_copy):
    from scripts.mvp_pipeline_cleanup import migrate

    migrate(real_db_copy)

    # Every non-K7 product with pipeline has exactly 1 row (analiza_koncowa)
    rows = real_db_copy.execute(
        "SELECT produkt, COUNT(*) AS n FROM produkt_pipeline "
        "WHERE produkt != 'Chegina_K7' GROUP BY produkt HAVING n > 1"
    ).fetchall()
    assert len(rows) == 0, (
        f"Non-K7 products still have multi-stage: "
        f"{[(r['produkt'], r['n']) for r in rows]}"
    )


def test_migrate_on_real_db_is_idempotent(real_db_copy):
    from scripts.mvp_pipeline_cleanup import migrate

    migrate(real_db_copy)
    before = real_db_copy.execute(
        "SELECT COUNT(*) AS n FROM produkt_pipeline"
    ).fetchone()["n"]

    migrate(real_db_copy)
    after = real_db_copy.execute(
        "SELECT COUNT(*) AS n FROM produkt_pipeline"
    ).fetchone()["n"]
    assert after == before
