"""Tests for batch card v2 — round inheritance logic."""

import sqlite3
import pytest

from mbr.models import init_mbr_tables
from mbr.pipeline.models import (
    add_etap_warunek,
    close_sesja,
    create_sesja,
    create_round_with_inheritance,
    evaluate_gate,
    get_etap_decyzje,
    get_pomiary,
    get_sesja,
    patch_parametry_etapy,
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


def test_get_etap_decyzje_returns_sorted_options(db):
    """get_etap_decyzje returns decisions filtered by typ, sorted by kolejnosc."""
    # etap_id=10 (sulfonowanie) already seeded in fixture
    # Seed 3 decisions: 2 fail, 1 pass
    db.execute(
        "INSERT INTO etap_decyzje (id, etap_id, typ, kod, label, akcja, wymaga_komentarza, kolejnosc) "
        "VALUES (1, 10, 'fail', 'new_round', 'Nowa runda', 'new_round', 0, 20)"
    )
    db.execute(
        "INSERT INTO etap_decyzje (id, etap_id, typ, kod, label, akcja, wymaga_komentarza, kolejnosc) "
        "VALUES (2, 10, 'fail', 'release_comment', 'Zwolnij z komentarzem', 'release', 1, 10)"
    )
    db.execute(
        "INSERT INTO etap_decyzje (id, etap_id, typ, kod, label, akcja, wymaga_komentarza, kolejnosc) "
        "VALUES (3, 10, 'pass', 'przejscie', 'Przejdź dalej', 'next_stage', 0, 1)"
    )
    db.commit()

    fail_opts = get_etap_decyzje(db, etap_id=10, typ='fail')
    assert len(fail_opts) == 2
    # Sorted by kolejnosc: 10, 20
    assert fail_opts[0]["kod"] == "release_comment"
    assert fail_opts[1]["kod"] == "new_round"
    # wymaga_komentarza preserved
    assert fail_opts[0]["wymaga_komentarza"] == 1
    assert fail_opts[1]["wymaga_komentarza"] == 0

    pass_opts = get_etap_decyzje(db, etap_id=10, typ='pass')
    assert len(pass_opts) == 1
    assert pass_opts[0]["kod"] == "przejscie"


def test_close_sesja_with_new_decision_codes(db):
    """close_sesja with 'release_comment' sets status, decyzja, komentarz_decyzji."""
    sesja_id = create_sesja(db, ebr_id=1, etap_id=10, runda=1, laborant="lab1")
    db.commit()

    close_sesja(db, sesja_id, decyzja='release_comment',
                komentarz='Dodatek wody z ręki')
    db.commit()

    sesja = get_sesja(db, sesja_id)
    assert sesja["status"] == "zamkniety"
    assert sesja["decyzja"] == "release_comment"
    assert sesja["komentarz_decyzji"] == "Dodatek wody z ręki"
    assert sesja["dt_end"] is not None


def test_global_edit_updates_limit(db):
    """PATCH endpoint should update parametry_etapy limits and set audit fields."""
    # Seed a parametry_etapy row
    db.execute("""
        INSERT INTO parametry_etapy (id, produkt, kontekst, parametr_id, min_limit, max_limit, kolejnosc)
        VALUES (999, 'K40GLO', 'sulfonowanie', 1, 0.0, 0.1, 1)
    """)
    db.commit()

    result = patch_parametry_etapy(db, pe_id=999, updates={"max_limit": 0.2, "min_limit": 0.05}, user_id=1)

    assert result["ok"] is True
    assert set(result["updated"]) == {"max_limit", "min_limit"}
    row = db.execute("SELECT * FROM parametry_etapy WHERE id = 999").fetchone()
    assert row["max_limit"] == 0.2
    assert row["min_limit"] == 0.05
    assert row["dt_modified"] is not None
    assert row["modified_by"] == 1


def test_global_edit_not_found(db):
    """patch_parametry_etapy returns not_found for missing row."""
    result = patch_parametry_etapy(db, pe_id=9999, updates={"max_limit": 1.0}, user_id=1)
    assert result["ok"] is False
    assert result["error"] == "not_found"


def test_close_with_new_round_creates_inherited_session(db):
    """Closing with new_round should create next round with inheritance."""
    sesja1 = create_sesja(db, ebr_id=1, etap_id=10, runda=1, laborant="lab1")
    db.execute("UPDATE ebr_etap_sesja SET status = 'w_trakcie' WHERE id = ?", (sesja1,))
    save_pomiar(db, sesja1, 901, 5.0, 0.0, 3.0, "lab1")   # so3 FAIL
    save_pomiar(db, sesja1, 902, 7.2, 6.0, 8.0, "lab1")    # ph OK
    db.commit()

    close_sesja(db, sesja1, decyzja="new_round")
    sesja2 = create_round_with_inheritance(db, 1, 10, sesja1, "lab1")
    db.commit()

    # Verify session 1 is closed
    s1 = db.execute("SELECT * FROM ebr_etap_sesja WHERE id = ?", (sesja1,)).fetchone()
    assert s1["status"] == "zamkniety"
    assert s1["decyzja"] == "new_round"

    # Verify session 2 exists with runda=2
    s2 = db.execute("SELECT * FROM ebr_etap_sesja WHERE id = ?", (sesja2,)).fetchone()
    assert s2["runda"] == 2

    # Verify inheritance: ph copied, so3 not
    pomiary2 = {p["parametr_id"]: p for p in get_pomiary(db, sesja2)}
    assert 902 in pomiary2  # ph
    assert 901 not in pomiary2  # so3


def test_close_with_release_comment_requires_komentarz(db):
    """release_comment stores komentarz_decyzji correctly."""
    sesja1 = create_sesja(db, ebr_id=1, etap_id=10, runda=1, laborant="lab1")
    db.execute("UPDATE ebr_etap_sesja SET status = 'w_trakcie' WHERE id = ?", (sesja1,))
    db.commit()

    # With komentarz — should work
    close_sesja(db, sesja1, decyzja="release_comment", komentarz="Dodatek wody z ręki")
    db.commit()
    s = db.execute("SELECT * FROM ebr_etap_sesja WHERE id = ?", (sesja1,)).fetchone()
    assert s["decyzja"] == "release_comment"
    assert s["komentarz_decyzji"] == "Dodatek wody z ręki"


def test_global_edit_no_valid_fields(db):
    """patch_parametry_etapy rejects payload with no allowed fields."""
    db.execute("""
        INSERT INTO parametry_etapy (id, produkt, kontekst, parametr_id, kolejnosc)
        VALUES (998, 'K40GLO', 'sulfonowanie', 1, 1)
    """)
    db.commit()

    result = patch_parametry_etapy(db, pe_id=998, updates={"bogus_field": 42}, user_id=1)
    assert result["ok"] is False
    assert result["error"] == "no_valid_fields"


def test_full_pipeline_flow_sulfonowanie_to_utlenianie(db):
    """E2E: sulfonowanie fail → new_round with inheritance → pass → close."""

    # ── Setup: gate condition SO₃²⁻ ≤ 0.1 for etap 10 (sulfonowanie) ──
    add_etap_warunek(db, etap_id=10, parametr_id=901,
                     operator="<=", wartosc=0.1,
                     opis_warunku="SO3 <= 0.1")
    db.commit()

    # ── Round 1: create session, enter SO₃ = 0.15 (FAIL) and pH = 7.2 (OK) ──
    s1 = create_sesja(db, ebr_id=1, etap_id=10, runda=1, laborant="lab1")
    save_pomiar(db, s1, parametr_id=901, wartosc=0.15,
                min_limit=0.0, max_limit=0.1, wpisal="lab1")
    save_pomiar(db, s1, parametr_id=902, wartosc=7.2,
                min_limit=6.0, max_limit=8.0, wpisal="lab1")
    db.commit()

    # ── Gate check round 1: should FAIL on SO₃ ──
    gate1 = evaluate_gate(db, etap_id=10, sesja_id=s1)
    assert gate1["passed"] is False
    assert len(gate1["failures"]) == 1
    assert gate1["failures"][0]["kod"] == "test_so3"

    # ── Close round 1 with new_round decision ──
    close_sesja(db, s1, decyzja="new_round")
    db.commit()

    s1_row = db.execute(
        "SELECT * FROM ebr_etap_sesja WHERE id = ?", (s1,)
    ).fetchone()
    assert s1_row["status"] == "zamkniety"
    assert s1_row["decyzja"] == "new_round"

    # ── Round 2: create with inheritance ──
    s2 = create_round_with_inheritance(db, ebr_id=1, etap_id=10,
                                       prev_sesja_id=s1, laborant="lab1")
    db.commit()

    # Verify round number
    s2_row = db.execute(
        "SELECT runda FROM ebr_etap_sesja WHERE id = ?", (s2,)
    ).fetchone()
    assert s2_row["runda"] == 2

    # Verify inheritance: pH copied (odziedziczony=1), SO₃ NOT copied
    pomiary2 = get_pomiary(db, s2)
    kody2 = {p["kod"] for p in pomiary2}
    assert "test_ph" in kody2, "pH should be inherited (was OK)"
    assert "test_so3" not in kody2, "SO3 should NOT be inherited (was FAIL)"

    for p in pomiary2:
        if p["kod"] == "test_ph":
            row = db.execute(
                "SELECT odziedziczony FROM ebr_pomiar WHERE id = ?", (p["id"],)
            ).fetchone()
            assert row["odziedziczony"] == 1
            assert p["wartosc"] == 7.2

    # ── Re-enter SO₃ in round 2: now 0.05 (OK) ──
    save_pomiar(db, s2, parametr_id=901, wartosc=0.05,
                min_limit=0.0, max_limit=0.1, wpisal="lab1")
    db.commit()

    # ── Gate check round 2: should PASS (SO₃ ≤ 0.1, pH inherited) ──
    gate2 = evaluate_gate(db, etap_id=10, sesja_id=s2)
    assert gate2["passed"] is True
    assert gate2["failures"] == []

    # ── Close round 2 with przejscie (pass) ──
    close_sesja(db, s2, decyzja="przejscie")
    db.commit()

    s2_closed = db.execute(
        "SELECT * FROM ebr_etap_sesja WHERE id = ?", (s2,)
    ).fetchone()
    assert s2_closed["status"] == "zamkniety"
    assert s2_closed["decyzja"] == "przejscie"
    assert s2_closed["dt_end"] is not None
