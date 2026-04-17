"""Tests for mbr/etapy/models.py — process stage analyses, corrections, and status tracking."""

import sqlite3
import pytest

from mbr.models import init_mbr_tables
from mbr.etapy.models import (
    save_etap_analizy,
    get_etap_analizy,
    add_korekta,
    confirm_korekta,
    get_korekty,
    get_process_stages,
    init_etapy_status,
    get_etapy_status,
    zatwierdz_etap,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# save_etap_analizy / get_etap_analizy
# ---------------------------------------------------------------------------

def test_save_etap_analizy_stores_values(db):
    save_etap_analizy(db, ebr_id=1, etap="amidowanie", runda=1,
                      wyniki={"ph_10proc": 11.76, "nd20": 1.3952}, user="tester")

    result = get_etap_analizy(db, ebr_id=1)
    assert "amidowanie" in result
    assert 1 in result["amidowanie"]
    assert result["amidowanie"][1]["ph_10proc"]["wartosc"] == pytest.approx(11.76)
    assert result["amidowanie"][1]["nd20"]["wartosc"] == pytest.approx(1.3952)


def test_save_etap_analizy_records_user(db):
    save_etap_analizy(db, ebr_id=1, etap="smca", runda=2,
                      wyniki={"ph": 10.5}, user="jkowalski")

    result = get_etap_analizy(db, ebr_id=1)
    assert result["smca"][2]["ph"]["wpisal"] == "jkowalski"


def test_save_etap_analizy_upsert(db):
    """Second save with same (ebr_id, etap, runda, kod) updates value."""
    save_etap_analizy(db, ebr_id=1, etap="utlenienie", runda=1,
                      wyniki={"ph": 7.0}, user="u1")
    save_etap_analizy(db, ebr_id=1, etap="utlenienie", runda=1,
                      wyniki={"ph": 7.5}, user="u2")

    result = get_etap_analizy(db, ebr_id=1)
    assert result["utlenienie"][1]["ph"]["wartosc"] == pytest.approx(7.5)
    assert result["utlenienie"][1]["ph"]["wpisal"] == "u2"


def test_save_etap_analizy_skips_none_and_empty(db):
    save_etap_analizy(db, ebr_id=1, etap="sulfonowanie", runda=1,
                      wyniki={"ph": None, "nd20": "", "sm": 42.0}, user="u")

    result = get_etap_analizy(db, ebr_id=1)
    assert "ph" not in result["sulfonowanie"][1]
    assert "nd20" not in result["sulfonowanie"][1]
    assert result["sulfonowanie"][1]["sm"]["wartosc"] == pytest.approx(42.0)


def test_get_etap_analizy_filtered_by_etap(db):
    save_etap_analizy(db, ebr_id=1, etap="amidowanie", runda=1,
                      wyniki={"ph": 11.0}, user="u")
    save_etap_analizy(db, ebr_id=1, etap="smca", runda=1,
                      wyniki={"ph": 9.0}, user="u")

    result = get_etap_analizy(db, ebr_id=1, etap="amidowanie")
    assert "amidowanie" in result
    assert "smca" not in result


def test_get_etap_analizy_nested_structure(db):
    """Returned dict has structure {etap: {runda: {kod: {wartosc, dt_wpisu, wpisal}}}}."""
    save_etap_analizy(db, ebr_id=5, etap="czwartorzedowanie", runda=3,
                      wyniki={"sm": 44.5}, user="lab")

    result = get_etap_analizy(db, ebr_id=5)
    entry = result["czwartorzedowanie"][3]["sm"]
    assert "wartosc" in entry
    assert "dt_wpisu" in entry
    assert "wpisal" in entry


def test_get_etap_analizy_empty_for_unknown_ebr(db):
    result = get_etap_analizy(db, ebr_id=9999)
    assert result == {}


# ---------------------------------------------------------------------------
# add_korekta / confirm_korekta / get_korekty
# ---------------------------------------------------------------------------

def test_add_korekta_returns_id(db):
    kid = add_korekta(db, ebr_id=1, etap="amidowanie", po_rundzie=1,
                      substancja="DMAPA", ilosc_kg=2.5, user="tech")
    assert isinstance(kid, int)
    assert kid > 0


def test_add_korekta_multiple_returns_distinct_ids(db):
    k1 = add_korekta(db, ebr_id=1, etap="amidowanie", po_rundzie=1,
                     substancja="DMAPA", ilosc_kg=1.0, user="u")
    k2 = add_korekta(db, ebr_id=1, etap="amidowanie", po_rundzie=2,
                     substancja="NaOH", ilosc_kg=0.5, user="u")
    assert k1 != k2


def test_confirm_korekta_marks_executed(db):
    kid = add_korekta(db, ebr_id=1, etap="smca", po_rundzie=1,
                      substancja="MCA", ilosc_kg=1.0, user="u")

    confirm_korekta(db, kid)

    row = db.execute("SELECT wykonano FROM ebr_korekty WHERE id = ?", (kid,)).fetchone()
    assert row["wykonano"] == 1


def test_confirm_korekta_sets_dt_wykonania(db):
    kid = add_korekta(db, ebr_id=1, etap="smca", po_rundzie=1,
                      substancja="MCA", ilosc_kg=1.0, user="u")
    confirm_korekta(db, kid)

    row = db.execute("SELECT dt_wykonania FROM ebr_korekty WHERE id = ?", (kid,)).fetchone()
    assert row["dt_wykonania"] is not None


def test_get_korekty_returns_list(db):
    add_korekta(db, ebr_id=2, etap="amidowanie", po_rundzie=1,
                substancja="DMAPA", ilosc_kg=2.0, user="u")
    add_korekta(db, ebr_id=2, etap="smca", po_rundzie=1,
                substancja="NaOH", ilosc_kg=0.3, user="u")

    korekty = get_korekty(db, ebr_id=2)
    assert len(korekty) == 2
    assert all(isinstance(k, dict) for k in korekty)


def test_get_korekty_filtered_by_etap(db):
    add_korekta(db, ebr_id=3, etap="amidowanie", po_rundzie=1,
                substancja="DMAPA", ilosc_kg=1.0, user="u")
    add_korekta(db, ebr_id=3, etap="smca", po_rundzie=1,
                substancja="MCA", ilosc_kg=0.5, user="u")

    korekty = get_korekty(db, ebr_id=3, etap="amidowanie")
    assert len(korekty) == 1
    assert korekty[0]["etap"] == "amidowanie"


def test_get_korekty_empty_for_no_matches(db):
    assert get_korekty(db, ebr_id=999) == []


# ---------------------------------------------------------------------------
# get_process_stages
# ---------------------------------------------------------------------------

def test_get_process_stages_k7_returns_3(db):
    """After MVP cleanup 2026-04-16 K7 has 3 process stages (sulfonowanie,
    utlenienie, standaryzacja). Pre-MVP was 5 stages (PROCESS_STAGES_K7)."""
    stages = get_process_stages("Chegina_K7")
    assert stages == ["sulfonowanie", "utlenienie", "standaryzacja"]


def test_get_process_stages_glol_returns_empty_after_mvp(db):
    """After MVP cleanup only K7 retains multi-stage workflow; GLOL products
    have empty produkt_etapy → get_process_stages returns []."""
    stages = get_process_stages("Chegina_K40GLOL")
    assert stages == []


def test_get_process_stages_simple_product_returns_empty(db):
    assert get_process_stages("Chegina_KK") == []
    assert get_process_stages("Chemipol_ML") == []
    assert get_process_stages("Monamid_K") == []


def test_get_process_stages_unknown_product_returns_empty(db):
    assert get_process_stages("UnknownProduct_XYZ") == []


def test_get_process_stages_k40gl_empty_after_mvp(db):
    """Post MVP K40GL has no produkt_etapy rows → empty workflow."""
    stages = get_process_stages("Chegina_K40GL")
    assert stages == []


# ---------------------------------------------------------------------------
# init_etapy_status
# ---------------------------------------------------------------------------
_K40GLO_PIPELINE_SKIP = "Pre-MVP pipeline assumed — deprecated after MVP cleanup 2026-04-16."


@pytest.mark.skip(reason=_K40GLO_PIPELINE_SKIP)
def test_init_etapy_status_creates_records(db):
    init_etapy_status(db, ebr_id=10, produkt="Chegina_K7")

    statuses = get_etapy_status(db, ebr_id=10)
    assert len(statuses) == 5
    etap_names = {s["etap"] for s in statuses}
    assert etap_names == {"amidowanie", "smca", "czwartorzedowanie", "sulfonowanie", "utlenienie"}


@pytest.mark.skip(reason=_K40GLO_PIPELINE_SKIP)
def test_init_etapy_status_parallel_stages_start_as_in_progress(db):
    init_etapy_status(db, ebr_id=11, produkt="Chegina_K7")

    statuses = {s["etap"]: s for s in get_etapy_status(db, ebr_id=11)}
    assert statuses["amidowanie"]["status"] == "in_progress"
    assert statuses["smca"]["status"] == "in_progress"


def test_init_etapy_status_non_parallel_stages_start_as_pending(db):
    """After MVP cleanup K7 has 3 process stages: sulfonowanie, utlenienie, standaryzacja.
    First stage (sulfonowanie) is in_progress, others are pending."""
    init_etapy_status(db, ebr_id=12, produkt="Chegina_K7")

    statuses = {s["etap"]: s for s in get_etapy_status(db, ebr_id=12)}
    assert statuses["utlenienie"]["status"] == "pending"
    assert statuses["standaryzacja"]["status"] == "pending"


@pytest.mark.skip(reason=_K40GLO_PIPELINE_SKIP)
def test_init_etapy_status_parallel_stages_have_dt_start(db):
    init_etapy_status(db, ebr_id=13, produkt="Chegina_K7")

    statuses = {s["etap"]: s for s in get_etapy_status(db, ebr_id=13)}
    assert statuses["amidowanie"]["dt_start"] is not None
    assert statuses["smca"]["dt_start"] is not None
    assert statuses["czwartorzedowanie"]["dt_start"] is None


def test_init_etapy_status_noop_for_simple_product(db):
    init_etapy_status(db, ebr_id=14, produkt="Chegina_KK")

    statuses = get_etapy_status(db, ebr_id=14)
    assert statuses == []


def test_init_etapy_status_glol_creates_no_stages_after_mvp(db):
    """Post MVP cleanup GLOL products have no process workflow — only K7 does."""
    init_etapy_status(db, ebr_id=15, produkt="Chegina_K40GLOL")

    statuses = get_etapy_status(db, ebr_id=15)
    assert statuses == []


# ---------------------------------------------------------------------------
# zatwierdz_etap — sequential flow
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason=_K40GLO_PIPELINE_SKIP)
def test_zatwierdz_etap_approves_and_returns_next(db):
    init_etapy_status(db, ebr_id=20, produkt="Chegina_K7")

    # After both parallel stages done, czwartorzedowanie becomes in_progress
    zatwierdz_etap(db, ebr_id=20, etap="amidowanie", user="u", produkt="Chegina_K7")
    result = zatwierdz_etap(db, ebr_id=20, etap="smca", user="u", produkt="Chegina_K7")

    assert result == "czwartorzedowanie"
    statuses = {s["etap"]: s for s in get_etapy_status(db, ebr_id=20)}
    assert statuses["czwartorzedowanie"]["status"] == "in_progress"


def test_zatwierdz_etap_sequential_advances(db):
    """After MVP cleanup K7 workflow is sulfonowanie → utlenienie → standaryzacja.
    Closing sulfonowanie returns 'utlenienie'."""
    init_etapy_status(db, ebr_id=21, produkt="Chegina_K7")
    next_e = zatwierdz_etap(db, ebr_id=21, etap="sulfonowanie", user="u", produkt="Chegina_K7")

    assert next_e == "utlenienie"


def test_zatwierdz_etap_last_stage_returns_none(db):
    """After MVP cleanup 2026-04-16 K7 workflow is {sulfonowanie, utlenienie,
    standaryzacja}. Closing the last stage returns None."""
    init_etapy_status(db, ebr_id=22, produkt="Chegina_K7")
    for etap in ("sulfonowanie", "utlenienie"):
        zatwierdz_etap(db, ebr_id=22, etap=etap, user="u", produkt="Chegina_K7")

    result = zatwierdz_etap(db, ebr_id=22, etap="standaryzacja", user="u", produkt="Chegina_K7")
    assert result is None


def test_zatwierdz_etap_marks_stage_as_done(db):
    """After MVP cleanup K7 first stage is sulfonowanie (not amidowanie)."""
    init_etapy_status(db, ebr_id=23, produkt="Chegina_K7")
    zatwierdz_etap(db, ebr_id=23, etap="sulfonowanie", user="operator", produkt="Chegina_K7")

    statuses = {s["etap"]: s for s in get_etapy_status(db, ebr_id=23)}
    assert statuses["sulfonowanie"]["status"] == "done"
    assert statuses["sulfonowanie"]["zatwierdzil"] == "operator"
    assert statuses["sulfonowanie"]["dt_end"] is not None


# ---------------------------------------------------------------------------
# zatwierdz_etap — parallel gate: czwartorzedowanie activates only when BOTH done
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason=_K40GLO_PIPELINE_SKIP)
def test_zatwierdz_etap_parallel_one_done_does_not_activate_czwartorzedowanie(db):
    init_etapy_status(db, ebr_id=30, produkt="Chegina_K7")

    result = zatwierdz_etap(db, ebr_id=30, etap="amidowanie", user="u", produkt="Chegina_K7")

    # smca still in_progress, so czwartorzedowanie must NOT be activated yet
    statuses = {s["etap"]: s for s in get_etapy_status(db, ebr_id=30)}
    assert statuses["czwartorzedowanie"]["status"] == "pending"
    # result should be the other parallel stage still in_progress
    assert result == "smca"


@pytest.mark.skip(reason=_K40GLO_PIPELINE_SKIP)
def test_zatwierdz_etap_parallel_both_done_activates_czwartorzedowanie(db):
    init_etapy_status(db, ebr_id=31, produkt="Chegina_K7")

    zatwierdz_etap(db, ebr_id=31, etap="amidowanie", user="u", produkt="Chegina_K7")
    result = zatwierdz_etap(db, ebr_id=31, etap="smca", user="u", produkt="Chegina_K7")

    statuses = {s["etap"]: s for s in get_etapy_status(db, ebr_id=31)}
    assert statuses["czwartorzedowanie"]["status"] == "in_progress"
    assert result == "czwartorzedowanie"
