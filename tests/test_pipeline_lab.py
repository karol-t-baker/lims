"""
tests/test_pipeline_lab.py — EBR execution: sessions, measurements, gates, corrections.
"""

import sqlite3
import pytest
from mbr.models import init_mbr_tables
from mbr.pipeline.models import (
    create_etap, add_etap_parametr, set_produkt_pipeline,
    add_etap_warunek, add_etap_korekta,
    create_sesja, get_sesja, list_sesje,
    save_pomiar, get_pomiary,
    evaluate_gate, close_sesja,
    create_ebr_korekta, list_ebr_korekty, update_ebr_korekta_status,
    init_pipeline_sesje,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed_param(db, pid, kod, typ="bezposredni"):
    db.execute(
        "INSERT OR IGNORE INTO parametry_analityczne (id, kod, label, typ) VALUES (?,?,?,?)",
        (pid, kod, kod, typ),
    )


def _seed_ebr(db, produkt="TestProd"):
    db.execute(
        """INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia)
           VALUES (1, ?, 1, '2026-01-01')""",
        (produkt,),
    )
    db.execute(
        """INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start)
           VALUES (1, 1, 'T-1', '1/2026', '2026-01-01')""",
    )
    return 1


@pytest.fixture
def setup_pipeline(db):
    """
    Create:
      - 2 etapy: sulfonowanie (cykliczny, id=1), analiza_koncowa (jednorazowy, id=2)
      - params: so3 (id=9001, max_limit=0.1), ph (id=9002)
      - etap_parametr: so3 on sulfonowanie, ph on sulfonowanie
      - warunek: so3 < 0.1 on sulfonowanie
      - korekta: Perhydrol on sulfonowanie
      - pipeline for TestProd: sulfonowanie (kolejnosc=1), analiza_koncowa (kolejnosc=2)
      - EBR batch
    """
    _seed_param(db, 9001, "so3")
    _seed_param(db, 9002, "ph")
    _seed_param(db, 9003, "aktywnosc")

    etap1 = create_etap(db, kod="sulfonowanie_test", nazwa="Sulfonowanie", typ_cyklu="cykliczny")
    etap2 = create_etap(db, kod="analiza_koncowa_test", nazwa="Analiza końcowa", typ_cyklu="jednorazowy")

    add_etap_parametr(db, etap1, 9001, kolejnosc=1, min_limit=None, max_limit=0.1)
    add_etap_parametr(db, etap1, 9002, kolejnosc=2)

    add_etap_warunek(db, etap1, 9001, operator="<", wartosc=0.1, opis_warunku="SO3 poniżej 0.1%")

    korekta_id = add_etap_korekta(db, etap1, substancja="Perhydrol", jednostka="kg", wykonawca="produkcja")

    set_produkt_pipeline(db, "TestProd", etap1, kolejnosc=1)
    set_produkt_pipeline(db, "TestProd", etap2, kolejnosc=2)

    _seed_ebr(db, produkt="TestProd")

    return {
        "etap1": etap1,
        "etap2": etap2,
        "ebr_id": 1,
        "korekta_typ_id": korekta_id,
        "p_so3": 9001,
        "p_ph": 9002,
    }


# ---------------------------------------------------------------------------
# Session tests
# ---------------------------------------------------------------------------

def test_create_sesja_and_get(setup_pipeline, db):
    ctx = setup_pipeline
    sesja_id = create_sesja(db, ctx["ebr_id"], ctx["etap1"], runda=1, laborant="Jan")
    assert sesja_id is not None and sesja_id > 0

    sesja = get_sesja(db, sesja_id)
    assert sesja is not None
    assert sesja["runda"] == 1
    assert sesja["status"] == "w_trakcie"
    assert sesja["laborant"] == "Jan"
    assert sesja["ebr_id"] == ctx["ebr_id"]
    assert sesja["etap_id"] == ctx["etap1"]
    assert sesja["dt_start"] is not None


def test_get_sesja_nonexistent(db):
    assert get_sesja(db, 99999) is None


def test_list_sesje_empty(setup_pipeline, db):
    ctx = setup_pipeline
    assert list_sesje(db, ctx["ebr_id"]) == []


def test_list_sesje(setup_pipeline, db):
    ctx = setup_pipeline
    create_sesja(db, ctx["ebr_id"], ctx["etap1"], runda=1)
    create_sesja(db, ctx["ebr_id"], ctx["etap1"], runda=2)
    create_sesja(db, ctx["ebr_id"], ctx["etap2"], runda=1)

    all_sesje = list_sesje(db, ctx["ebr_id"])
    assert len(all_sesje) == 3

    # filter by etap_id
    etap1_sesje = list_sesje(db, ctx["ebr_id"], etap_id=ctx["etap1"])
    assert len(etap1_sesje) == 2
    assert all(s["etap_id"] == ctx["etap1"] for s in etap1_sesje)


# ---------------------------------------------------------------------------
# Pomiar tests
# ---------------------------------------------------------------------------

def test_save_pomiar_and_get(setup_pipeline, db):
    ctx = setup_pipeline
    sesja_id = create_sesja(db, ctx["ebr_id"], ctx["etap1"])

    pomiar_id = save_pomiar(
        db, sesja_id, ctx["p_so3"],
        wartosc=0.05, min_limit=None, max_limit=0.1,
        wpisal="Jan", is_manual=1,
    )
    assert pomiar_id > 0

    pomiary = get_pomiary(db, sesja_id)
    assert len(pomiary) == 1
    p = pomiary[0]
    assert p["wartosc"] == pytest.approx(0.05)
    assert p["w_limicie"] == 1
    assert p["kod"] == "so3"


def test_save_pomiar_out_of_limit(setup_pipeline, db):
    ctx = setup_pipeline
    sesja_id = create_sesja(db, ctx["ebr_id"], ctx["etap1"])

    save_pomiar(
        db, sesja_id, ctx["p_so3"],
        wartosc=0.15, min_limit=None, max_limit=0.1,
        wpisal="Jan",
    )

    pomiary = get_pomiary(db, sesja_id)
    assert pomiary[0]["w_limicie"] == 0


def test_save_pomiar_no_limits(setup_pipeline, db):
    ctx = setup_pipeline
    sesja_id = create_sesja(db, ctx["ebr_id"], ctx["etap1"])

    save_pomiar(
        db, sesja_id, ctx["p_ph"],
        wartosc=7.5, min_limit=None, max_limit=None,
        wpisal="Jan",
    )

    pomiary = get_pomiary(db, sesja_id)
    ph = next(p for p in pomiary if p["kod"] == "ph")
    assert ph["w_limicie"] is None


def test_save_pomiar_upsert(setup_pipeline, db):
    """Saving same parametr twice should update, not duplicate."""
    ctx = setup_pipeline
    sesja_id = create_sesja(db, ctx["ebr_id"], ctx["etap1"])

    save_pomiar(db, sesja_id, ctx["p_so3"], wartosc=0.05, min_limit=None, max_limit=0.1, wpisal="Jan")
    save_pomiar(db, sesja_id, ctx["p_so3"], wartosc=0.08, min_limit=None, max_limit=0.1, wpisal="Jan")

    pomiary = get_pomiary(db, sesja_id)
    so3_rows = [p for p in pomiary if p["kod"] == "so3"]
    assert len(so3_rows) == 1
    assert so3_rows[0]["wartosc"] == pytest.approx(0.08)


def test_save_pomiar_min_limit_check(setup_pipeline, db):
    """Value below min_limit => w_limicie=0."""
    ctx = setup_pipeline
    sesja_id = create_sesja(db, ctx["ebr_id"], ctx["etap1"])

    save_pomiar(db, sesja_id, ctx["p_ph"], wartosc=3.0, min_limit=5.0, max_limit=9.0, wpisal="Jan")
    pomiary = get_pomiary(db, sesja_id)
    ph = next(p for p in pomiary if p["kod"] == "ph")
    assert ph["w_limicie"] == 0


# ---------------------------------------------------------------------------
# Gate evaluation tests
# ---------------------------------------------------------------------------

def test_evaluate_gate_pass(setup_pipeline, db):
    ctx = setup_pipeline
    sesja_id = create_sesja(db, ctx["ebr_id"], ctx["etap1"])
    save_pomiar(db, sesja_id, ctx["p_so3"], wartosc=0.05, min_limit=None, max_limit=0.1, wpisal="Jan")

    result = evaluate_gate(db, ctx["etap1"], sesja_id)
    assert result["passed"] is True
    assert result["failures"] == []


def test_evaluate_gate_fail(setup_pipeline, db):
    ctx = setup_pipeline
    sesja_id = create_sesja(db, ctx["ebr_id"], ctx["etap1"])
    save_pomiar(db, sesja_id, ctx["p_so3"], wartosc=0.15, min_limit=None, max_limit=0.1, wpisal="Jan")

    result = evaluate_gate(db, ctx["etap1"], sesja_id)
    assert result["passed"] is False
    assert len(result["failures"]) == 1
    f = result["failures"][0]
    assert f["kod"] == "so3"


def test_evaluate_gate_missing_measurement(setup_pipeline, db):
    """No pomiar for warunek parametr => gate fails."""
    ctx = setup_pipeline
    sesja_id = create_sesja(db, ctx["ebr_id"], ctx["etap1"])
    # Don't add so3 measurement

    result = evaluate_gate(db, ctx["etap1"], sesja_id)
    assert result["passed"] is False
    assert len(result["failures"]) == 1


def test_evaluate_gate_no_warunki(setup_pipeline, db):
    """etap2 has no warunki — gate always passes."""
    ctx = setup_pipeline
    sesja_id = create_sesja(db, ctx["ebr_id"], ctx["etap2"])

    result = evaluate_gate(db, ctx["etap2"], sesja_id)
    assert result["passed"] is True
    assert result["failures"] == []


# ---------------------------------------------------------------------------
# close_sesja tests
# ---------------------------------------------------------------------------

def test_close_sesja_przejscie(setup_pipeline, db):
    ctx = setup_pipeline
    sesja_id = create_sesja(db, ctx["ebr_id"], ctx["etap1"])
    close_sesja(db, sesja_id, decyzja="przejscie")

    sesja = get_sesja(db, sesja_id)
    assert sesja["status"] == "ok"
    assert sesja["dt_end"] is not None
    assert sesja["decyzja"] == "przejscie"


def test_close_sesja_korekta(setup_pipeline, db):
    ctx = setup_pipeline
    sesja_id = create_sesja(db, ctx["ebr_id"], ctx["etap1"])
    close_sesja(db, sesja_id, decyzja="korekta")

    sesja = get_sesja(db, sesja_id)
    assert sesja["status"] == "oczekuje_korekty"
    assert sesja["dt_end"] is not None
    assert sesja["decyzja"] == "korekta"


# ---------------------------------------------------------------------------
# Korekta tests
# ---------------------------------------------------------------------------

def test_create_ebr_korekta_and_list(setup_pipeline, db):
    ctx = setup_pipeline
    sesja_id = create_sesja(db, ctx["ebr_id"], ctx["etap1"])

    korekta_id = create_ebr_korekta(
        db, sesja_id, ctx["korekta_typ_id"],
        ilosc=2.5, zalecil="Jan"
    )
    assert korekta_id > 0

    korekty = list_ebr_korekty(db, sesja_id)
    assert len(korekty) == 1
    k = korekty[0]
    assert k["ilosc"] == pytest.approx(2.5)
    assert k["zalecil"] == "Jan"
    assert k["substancja"] == "Perhydrol"
    assert k["status"] == "zalecona"
    assert k["dt_zalecenia"] is not None


def test_update_ebr_korekta_status(setup_pipeline, db):
    ctx = setup_pipeline
    sesja_id = create_sesja(db, ctx["ebr_id"], ctx["etap1"])
    korekta_id = create_ebr_korekta(db, sesja_id, ctx["korekta_typ_id"], ilosc=1.0, zalecil="Jan")

    update_ebr_korekta_status(db, korekta_id, status="wykonana", wykonawca_info="Piotr")

    korekty = list_ebr_korekty(db, sesja_id)
    k = korekty[0]
    assert k["status"] == "wykonana"
    assert k["wykonawca_info"] == "Piotr"
    assert k["dt_wykonania"] is not None


def test_update_ebr_korekta_status_anulowana(setup_pipeline, db):
    ctx = setup_pipeline
    sesja_id = create_sesja(db, ctx["ebr_id"], ctx["etap1"])
    korekta_id = create_ebr_korekta(db, sesja_id, ctx["korekta_typ_id"], ilosc=1.0, zalecil="Jan")

    update_ebr_korekta_status(db, korekta_id, status="anulowana")

    korekty = list_ebr_korekty(db, sesja_id)
    assert korekty[0]["status"] == "anulowana"


# ---------------------------------------------------------------------------
# init_pipeline_sesje tests
# ---------------------------------------------------------------------------

def test_init_pipeline_sesje(setup_pipeline, db):
    ctx = setup_pipeline
    sesja_id = init_pipeline_sesje(db, ctx["ebr_id"], "TestProd", laborant="Anna")
    assert sesja_id is not None

    sesja = get_sesja(db, sesja_id)
    assert sesja["etap_id"] == ctx["etap1"]  # first stage only
    assert sesja["runda"] == 1
    assert sesja["laborant"] == "Anna"

    # Only one session should exist
    all_sesje = list_sesje(db, ctx["ebr_id"])
    assert len(all_sesje) == 1


def test_init_pipeline_sesje_no_pipeline(db):
    """No pipeline configured for product — returns None."""
    db.execute(
        """INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia)
           VALUES (1, 'NoPiplineProd', 1, '2026-01-01')"""
    )
    db.execute(
        """INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start)
           VALUES (1, 1, 'NP-1', '1/2026', '2026-01-01')"""
    )
    result = init_pipeline_sesje(db, 1, "NoPiplineProd")
    assert result is None


# ---------------------------------------------------------------------------
# Multi-round flow integration test
# ---------------------------------------------------------------------------

def test_multi_round_flow(setup_pipeline, db):
    """
    Round 1: measure so3=0.15 (fail), close korekta, add korekta, execute korekta.
    Round 2: measure so3=0.05 (pass), close przejscie.
    """
    ctx = setup_pipeline
    ebr_id = ctx["ebr_id"]

    # Round 1
    s1 = create_sesja(db, ebr_id, ctx["etap1"], runda=1, laborant="Jan")
    save_pomiar(db, s1, ctx["p_so3"], wartosc=0.15, min_limit=None, max_limit=0.1, wpisal="Jan")
    gate1 = evaluate_gate(db, ctx["etap1"], s1)
    assert gate1["passed"] is False

    close_sesja(db, s1, decyzja="korekta")
    sesja1 = get_sesja(db, s1)
    assert sesja1["status"] == "oczekuje_korekty"

    # Add and execute korekta
    k_id = create_ebr_korekta(db, s1, ctx["korekta_typ_id"], ilosc=3.0, zalecil="Jan")
    update_ebr_korekta_status(db, k_id, status="wykonana", wykonawca_info="Produkcja")
    korekty = list_ebr_korekty(db, s1)
    assert korekty[0]["status"] == "wykonana"

    # Round 2
    s2 = create_sesja(db, ebr_id, ctx["etap1"], runda=2, laborant="Jan")
    save_pomiar(db, s2, ctx["p_so3"], wartosc=0.05, min_limit=None, max_limit=0.1, wpisal="Jan")
    gate2 = evaluate_gate(db, ctx["etap1"], s2)
    assert gate2["passed"] is True

    close_sesja(db, s2, decyzja="przejscie")
    sesja2 = get_sesja(db, s2)
    assert sesja2["status"] == "ok"

    # Two sessions for etap1
    sesje = list_sesje(db, ebr_id, etap_id=ctx["etap1"])
    assert len(sesje) == 2
    assert sesje[0]["runda"] == 1
    assert sesje[1]["runda"] == 2
