"""Tests for auto-append of pakowanie_bezposrednie annotation to uwagi_koncowe."""
import sqlite3
import pytest

from mbr.models import init_mbr_tables
from mbr.laborant.models import complete_ebr


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _mk_ebr(db, pakowanie=None, uwagi=None) -> int:
    """Create minimal MBR + EBR with optional pakowanie_bezposrednie/uwagi_koncowe."""
    cur = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, dt_utworzenia) "
        "VALUES ('TestProd', 1, 'active', '[]', '{}', datetime('now'))"
    )
    mbr_id = cur.lastrowid
    cur = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, "
        "pakowanie_bezposrednie, uwagi_koncowe) "
        "VALUES (?, 'B001', '1/2026', datetime('now'), 'open', ?, ?)",
        (mbr_id, pakowanie, uwagi),
    )
    db.commit()
    return cur.lastrowid


def _uwagi_after(db, ebr_id):
    return db.execute(
        "SELECT uwagi_koncowe FROM ebr_batches WHERE ebr_id=?", (ebr_id,),
    ).fetchone()["uwagi_koncowe"]


def test_ibc_empty_uwagi_becomes_ibc(db):
    """IBC + no prior uwagi → uwagi_koncowe == 'IBC'."""
    ebr_id = _mk_ebr(db, pakowanie="IBC", uwagi=None)
    complete_ebr(db, ebr_id)
    assert _uwagi_after(db, ebr_id) == "IBC"


def test_beczki_appends_with_newline(db):
    """Beczki + existing uwagi → '<existing>\\nBeczki'."""
    ebr_id = _mk_ebr(db, pakowanie="Beczki", uwagi="Lepkość 2,5")
    complete_ebr(db, ebr_id)
    assert _uwagi_after(db, ebr_id) == "Lepkość 2,5\nBeczki"


def test_double_complete_is_idempotent(db):
    """Calling complete_ebr twice does not duplicate the annotation."""
    ebr_id = _mk_ebr(db, pakowanie="Beczki", uwagi="Lepkość 2,5")
    complete_ebr(db, ebr_id)
    complete_ebr(db, ebr_id)
    assert _uwagi_after(db, ebr_id) == "Lepkość 2,5\nBeczki"


def test_existing_manual_ibc_not_duplicated(db):
    """Word-boundary + case-insensitive: manual 'ibc' in uwagi blocks auto-append."""
    ebr_id = _mk_ebr(db, pakowanie="IBC", uwagi="już wpisałem ibc ręcznie")
    complete_ebr(db, ebr_id)
    assert _uwagi_after(db, ebr_id) == "już wpisałem ibc ręcznie"


def test_null_pakowanie_leaves_uwagi_unchanged(db):
    """pakowanie_bezposrednie=NULL → no annotation."""
    ebr_id = _mk_ebr(db, pakowanie=None, uwagi="Lepkość OK")
    complete_ebr(db, ebr_id)
    assert _uwagi_after(db, ebr_id) == "Lepkość OK"


def test_non_whitelisted_pakowanie_leaves_uwagi_unchanged(db):
    """Value outside whitelist ('xyz') → no annotation."""
    ebr_id = _mk_ebr(db, pakowanie="xyz", uwagi=None)
    complete_ebr(db, ebr_id)
    # uwagi_koncowe stays None (not set to 'xyz')
    assert _uwagi_after(db, ebr_id) is None
