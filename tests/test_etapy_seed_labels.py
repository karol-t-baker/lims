"""Regression: K7 process-stage labels clearly mark analytical checkpoints.

After init_mbr_tables(), the three K7 stages (sulfonowanie, utlenienie,
standaryzacja) must carry 'Analiza po …' labels — the 'Sulfonowanie' /
'Utlenienie' / 'Standaryzacja' originals were ambiguous with the chemical
phases themselves and confused operators.

Note: these defaults live in etapy_procesowe (seeded by init_mbr_tables).
The etapy_analityczne table is populated by prod DB migration (Task 5).
"""

import sqlite3
import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def test_k7_stage_nazwa_uses_analiza_po_prefix(db):
    rows = dict(
        db.execute(
            "SELECT kod, label FROM etapy_procesowe "
            "WHERE kod IN ('sulfonowanie','utlenienie','standaryzacja')"
        ).fetchall()
    )
    assert rows["sulfonowanie"]  == "Analiza po sulfonowaniu"
    assert rows["utlenienie"]    == "Analiza po utlenianiu"
    assert rows["standaryzacja"] == "Analiza po standaryzacji"


def test_analiza_koncowa_label_unchanged(db):
    """4th stage (analiza_koncowa) is already clearly named — keep it."""
    row = db.execute(
        "SELECT label FROM etapy_procesowe WHERE kod = 'analiza_koncowa'"
    ).fetchone()
    assert row["label"] == "Analiza końcowa"
