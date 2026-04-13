"""Tests for batch card v2 — round inheritance logic."""

import sqlite3
import pytest

from mbr.models import init_mbr_tables
from mbr.pipeline.models import (
    create_sesja,
    create_round_with_inheritance,
    get_pomiary,
    save_pomiar,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_mbr_tables(conn)
    # Seed: parametry_analityczne, ebr_batches, etapy_analityczne
    conn.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision) "
        "VALUES (901, 'test_so3', 'Siarczyny', 'titracja', 3)"
    )
    conn.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision) "
        "VALUES (902, 'test_ph', 'pH', 'bezposredni', 1)"
    )
    conn.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision) "
        "VALUES (903, 'test_sm', 'Sucha masa', 'bezposredni', 1)"
    )
    conn.execute(
        "INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, etapy_json, parametry_lab, dt_utworzenia) "
        "VALUES (1, 'K40GLO', 1, 'active', '[]', '{}', '2026-01-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, typ, status, dt_start) "
        "VALUES (1, 1, 'TEST-001-1', 'TEST-001', 'szarza', 'open', '2026-01-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
        "VALUES (10, 'sulfonowanie', 'Sulfonowanie', 'cykliczny')"
    )
    conn.commit()
    yield conn
    conn.close()


def test_create_round_with_inheritance_copies_ok_skips_fail(db):
    """Round 2 should inherit OK and NULL-limit measurements, skip FAIL."""
    # Create round 1 session
    sesja1 = create_sesja(db, ebr_id=1, etap_id=10, runda=1, laborant="lab1")

    # so3 = FAIL (w_limicie=0)
    save_pomiar(db, sesja1, parametr_id=901, wartosc=5.0,
                min_limit=0.0, max_limit=3.0, wpisal="lab1")
    # ph = OK (w_limicie=1)
    save_pomiar(db, sesja1, parametr_id=902, wartosc=7.0,
                min_limit=6.0, max_limit=8.0, wpisal="lab1")
    # sm = no limit (w_limicie=NULL)
    save_pomiar(db, sesja1, parametr_id=903, wartosc=42.0,
                min_limit=None, max_limit=None, wpisal="lab1")
    db.commit()

    # Create round 2 with inheritance
    sesja2 = create_round_with_inheritance(
        db, ebr_id=1, etap_id=10, prev_sesja_id=sesja1, laborant="lab2"
    )

    pomiary = get_pomiary(db, sesja2)
    kody = {p["kod"] for p in pomiary}

    # ph and sm should be inherited, so3 should NOT
    assert "test_ph" in kody
    assert "test_sm" in kody
    assert "test_so3" not in kody
    assert len(pomiary) == 2

    # All inherited measurements should have odziedziczony = 1
    for p in pomiary:
        row = db.execute(
            "SELECT odziedziczony FROM ebr_pomiar WHERE id = ?", (p["id"],)
        ).fetchone()
        assert row["odziedziczony"] == 1


def test_inherited_measurement_preserves_limits(db):
    """Copied measurements must keep their min_limit, max_limit, w_limicie."""
    sesja1 = create_sesja(db, ebr_id=1, etap_id=10, runda=1, laborant="lab1")

    # ph = OK with specific limits
    save_pomiar(db, sesja1, parametr_id=902, wartosc=7.5,
                min_limit=6.0, max_limit=8.0, wpisal="lab1")
    # sm = no limits
    save_pomiar(db, sesja1, parametr_id=903, wartosc=42.0,
                min_limit=None, max_limit=None, wpisal="lab1")
    db.commit()

    sesja2 = create_round_with_inheritance(
        db, ebr_id=1, etap_id=10, prev_sesja_id=sesja1, laborant="lab2"
    )

    pomiary = get_pomiary(db, sesja2)
    by_kod = {p["kod"]: p for p in pomiary}

    # ph limits preserved
    ph = by_kod["test_ph"]
    assert ph["min_limit"] == 6.0
    assert ph["max_limit"] == 8.0
    assert ph["w_limicie"] == 1
    assert ph["wartosc"] == 7.5

    # sm has no limits
    sm = by_kod["test_sm"]
    assert sm["min_limit"] is None
    assert sm["max_limit"] is None
    assert sm["w_limicie"] is None

    # Verify round number
    sesja_row = db.execute(
        "SELECT runda FROM ebr_etap_sesja WHERE id = ?", (sesja2,)
    ).fetchone()
    assert sesja_row["runda"] == 2
