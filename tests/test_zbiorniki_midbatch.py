"""Tests for mid-batch zbiornik assignment — link/unlink + preservation at completion."""

import sqlite3

import pytest

from mbr.models import init_mbr_tables
from mbr.zbiorniki.models import (
    link_szarza,
    unlink_szarza,
    get_links_for_ebr,
    create_zbiornik,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    try:
        conn.execute("ALTER TABLE ebr_batches ADD COLUMN nr_zbiornika TEXT")
    except Exception:
        pass
    conn.commit()
    yield conn
    conn.close()


def _mk_batch(db, produkt="Chegina_K7", typ="szarza", status="open"):
    mbr = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "dt_utworzenia) VALUES (?, 1, 'active', '[]', '{}', datetime('now'))",
        (produkt,),
    ).lastrowid
    ebr = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, typ) "
        "VALUES (?, ?, ?, datetime('now'), ?, ?)",
        (mbr, f"B-{produkt}-1", "1/26", status, typ),
    ).lastrowid
    db.commit()
    return ebr


def test_link_szarza_midbatch_creates_row(db):
    ebr = _mk_batch(db)
    zid = create_zbiornik(db, "M90", 5000, "Chegina_K7")
    link_id = link_szarza(db, ebr, zid)
    assert isinstance(link_id, int)

    links = get_links_for_ebr(db, ebr)
    assert len(links) == 1
    assert links[0]["zbiornik_id"] == zid
    assert links[0]["nr_zbiornika"] == "M90"


def test_link_szarza_masa_kg_null_when_not_provided(db):
    """Mid-batch link (no masa) stores NULL; pump modal fills it at completion."""
    ebr = _mk_batch(db)
    zid = create_zbiornik(db, "M91", 3000, "Chegina_K7")
    link_szarza(db, ebr, zid)  # No masa_kg passed
    row = db.execute(
        "SELECT masa_kg FROM zbiornik_szarze WHERE ebr_id=? AND zbiornik_id=?",
        (ebr, zid),
    ).fetchone()
    assert row["masa_kg"] is None


def test_unlink_szarza_removes_row(db):
    ebr = _mk_batch(db)
    zid = create_zbiornik(db, "M92", 3000, "Chegina_K7")
    link_id = link_szarza(db, ebr, zid)
    unlink_szarza(db, link_id)
    assert get_links_for_ebr(db, ebr) == []


def test_multiple_midbatch_links_accumulate(db):
    ebr = _mk_batch(db)
    z1 = create_zbiornik(db, "M93", 2000, "Chegina_K7")
    z2 = create_zbiornik(db, "M94", 3000, "Chegina_K7")
    link_szarza(db, ebr, z1)
    link_szarza(db, ebr, z2)
    links = get_links_for_ebr(db, ebr)
    assert len(links) == 2
    nrs = sorted(l["nr_zbiornika"] for l in links)
    assert nrs == ["M93", "M94"]


def test_midbatch_links_survive_until_completion(db):
    """Mid-batch link persists — pump modal at completion can read them."""
    ebr = _mk_batch(db)
    zid = create_zbiornik(db, "M95", 4000, "Chegina_K7")
    link_szarza(db, ebr, zid)

    # Simulate completion: pump modal reads via get_links_for_ebr
    pre_completion_links = get_links_for_ebr(db, ebr)
    assert len(pre_completion_links) == 1
    assert pre_completion_links[0]["nr_zbiornika"] == "M95"
