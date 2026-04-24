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
    assert sesja["status"] == "nierozpoczety"
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

def test_close_sesja_zamknij(setup_pipeline, db):
    ctx = setup_pipeline
    sesja_id = create_sesja(db, ctx["ebr_id"], ctx["etap1"])
    close_sesja(db, sesja_id, decyzja="zamknij_etap")

    sesja = get_sesja(db, sesja_id)
    assert sesja["status"] == "zamkniety"
    assert sesja["dt_end"] is not None
    assert sesja["decyzja"] == "zamknij_etap"


def test_close_sesja_reopen(setup_pipeline, db):
    ctx = setup_pipeline
    sesja_id = create_sesja(db, ctx["ebr_id"], ctx["etap1"])
    close_sesja(db, sesja_id, decyzja="reopen_etap")

    sesja = get_sesja(db, sesja_id)
    assert sesja["status"] == "w_trakcie"
    assert sesja["dt_end"] is not None
    assert sesja["decyzja"] == "reopen_etap"


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
    Round 1: measure so3=0.15 (fail), close stage, add korekta, execute korekta.
    Round 2: measure so3=0.05 (pass), close stage.
    """
    ctx = setup_pipeline
    ebr_id = ctx["ebr_id"]

    # Round 1
    s1 = create_sesja(db, ebr_id, ctx["etap1"], runda=1, laborant="Jan")
    save_pomiar(db, s1, ctx["p_so3"], wartosc=0.15, min_limit=None, max_limit=0.1, wpisal="Jan")
    gate1 = evaluate_gate(db, ctx["etap1"], s1)
    assert gate1["passed"] is False

    close_sesja(db, s1, decyzja="zamknij_etap")
    sesja1 = get_sesja(db, s1)
    assert sesja1["status"] == "zamkniety"

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

    close_sesja(db, s2, decyzja="zamknij_etap")
    sesja2 = get_sesja(db, s2)
    assert sesja2["status"] == "zamkniety"

    # Two sessions for etap1
    sesje = list_sesje(db, ebr_id, etap_id=ctx["etap1"])
    assert len(sesje) == 2
    assert sesje[0]["runda"] == 1
    assert sesje[1]["runda"] == 2


# ---------------------------------------------------------------------------
# Client fixture for HTTP testing
# ---------------------------------------------------------------------------

class _DBWrapper:
    """Wraps sqlite3 Connection, making close() a no-op for testing."""
    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self):
        """No-op close to preserve connection across requests."""
        pass


def _make_client_for_pipeline(monkeypatch, db):
    """Build a Flask test client with the in-memory db monkey-patched in."""
    from contextlib import contextmanager
    import mbr.db
    import mbr.pipeline.lab_routes

    # Wrap the db so close() is a no-op (preserve connection across requests)
    wrapped_db = _DBWrapper(db)

    # Monkeypatch get_db to return the in-memory db
    def fake_get_db():
        return wrapped_db

    @contextmanager
    def fake_db_session():
        yield wrapped_db

    monkeypatch.setattr(mbr.db, "get_db", fake_get_db)
    monkeypatch.setattr(mbr.pipeline.lab_routes, "get_db", fake_get_db)
    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": "laborant", "worker_id": None}
    return client


@pytest.fixture
def client(monkeypatch, db):
    return _make_client_for_pipeline(monkeypatch, db)


# ---------------------------------------------------------------------------
# PUT /api/pipeline/lab/ebr/<ebr_id>/korekta — per-field auto-save
# ---------------------------------------------------------------------------

def _seed_pipeline_fixture_for_korekta(db):
    """Seed etap + korekta catalog + mbr + ebr + open sesja.
    Returns dict with ids used by the tests."""
    db.execute(
        "INSERT OR IGNORE INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
        "VALUES (910, 'sulfon_lab_t', 'Sulfonowanie (test)', 'cykliczny')"
    )
    db.execute(
        "INSERT INTO etap_korekty_katalog "
        "(id, etap_id, substancja, jednostka, wykonawca, kolejnosc) "
        "VALUES (910, 910, 'Perhydrol 34%', 'kg', 'produkcja', 1)"
    )
    from datetime import datetime
    mbr_id = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, dt_utworzenia) "
        "VALUES ('TESTPROD', 1, 'active', datetime('now')) RETURNING mbr_id"
    ).fetchone()["mbr_id"]
    ebr_id = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, typ) "
        "VALUES (?, 'B-KOR-1', '1/KOR', datetime('now'), 'szarza') "
        "RETURNING ebr_id",
        (mbr_id,),
    ).fetchone()["ebr_id"]
    from mbr.pipeline.models import create_sesja
    sesja_id = create_sesja(db, ebr_id, 910, runda=1, laborant="lab1")
    db.commit()
    return {"ebr_id": ebr_id, "etap_id": 910, "sesja_id": sesja_id,
            "perhydrol_typ_id": 910}


def test_put_korekta_creates_new_row(client, db):
    s = _seed_pipeline_fixture_for_korekta(db)
    resp = client.put(
        f"/api/pipeline/lab/ebr/{s['ebr_id']}/korekta",
        json={"etap_id": s["etap_id"], "substancja": "Perhydrol 34%",
              "ilosc": 12.5, "ilosc_wyliczona": 11.8},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["sesja_id"] == s["sesja_id"]
    assert data["korekta_typ_id"] == s["perhydrol_typ_id"]
    assert data["ilosc"] == 12.5
    assert data["ilosc_wyliczona"] == 11.8


def test_put_korekta_updates_existing(client, db):
    s = _seed_pipeline_fixture_for_korekta(db)
    url = f"/api/pipeline/lab/ebr/{s['ebr_id']}/korekta"
    body = {"etap_id": s["etap_id"], "substancja": "Perhydrol 34%",
            "ilosc_wyliczona": 11.8}
    client.put(url, json={**body, "ilosc": 10.0})
    client.put(url, json={**body, "ilosc": 15.5})
    n = db.execute(
        "SELECT COUNT(*) AS n FROM ebr_korekta_v2 "
        "WHERE sesja_id=? AND korekta_typ_id=?",
        (s["sesja_id"], s["perhydrol_typ_id"]),
    ).fetchone()["n"]
    assert n == 1


def test_put_korekta_ilosc_null_clears_manual(client, db):
    s = _seed_pipeline_fixture_for_korekta(db)
    url = f"/api/pipeline/lab/ebr/{s['ebr_id']}/korekta"
    body = {"etap_id": s["etap_id"], "substancja": "Perhydrol 34%",
            "ilosc_wyliczona": 11.8}
    client.put(url, json={**body, "ilosc": 12.5})
    client.put(url, json={**body, "ilosc": None})
    row = db.execute(
        "SELECT ilosc FROM ebr_korekta_v2 "
        "WHERE sesja_id=? AND korekta_typ_id=?",
        (s["sesja_id"], s["perhydrol_typ_id"]),
    ).fetchone()
    assert row["ilosc"] is None


def test_put_korekta_unknown_substancja_returns_404(client, db):
    s = _seed_pipeline_fixture_for_korekta(db)
    resp = client.put(
        f"/api/pipeline/lab/ebr/{s['ebr_id']}/korekta",
        json={"etap_id": s["etap_id"], "substancja": "NieMaTakiej",
              "ilosc": 1.0},
    )
    assert resp.status_code == 404


def test_put_korekta_missing_fields_returns_400(client, db):
    s = _seed_pipeline_fixture_for_korekta(db)
    resp = client.put(
        f"/api/pipeline/lab/ebr/{s['ebr_id']}/korekta",
        json={"etap_id": s["etap_id"]},  # substancja + ilosc missing
    )
    assert resp.status_code == 400


def test_put_korekta_zalecil_uses_shift_worker_initials(client, db):
    """zalecil on auto-save should be shift worker initials (like POST does),
    not the Flask session login. Prevents the double-log bug where PUT saved
    'lab' and POST saved worker initials as two separate rows."""
    s = _seed_pipeline_fixture_for_korekta(db)
    wid = db.execute(
        "INSERT INTO workers (imie, nazwisko, inicjaly, nickname) "
        "VALUES ('Jan', 'Kowalski', 'JK', 'Janek') RETURNING id"
    ).fetchone()["id"]
    db.commit()
    with client.session_transaction() as sess:
        sess["shift_workers"] = [wid]

    resp = client.put(
        f"/api/pipeline/lab/ebr/{s['ebr_id']}/korekta",
        json={"etap_id": s["etap_id"], "substancja": "Perhydrol 34%",
              "ilosc": 5.0},
    )
    assert resp.status_code == 200
    row = db.execute(
        "SELECT zalecil FROM ebr_korekta_v2 WHERE sesja_id=?", (s["sesja_id"],)
    ).fetchone()
    assert row["zalecil"] == "JK", \
        f"expected 'JK' (initials from shift worker), got {row['zalecil']!r}"


def test_put_korekta_attribution_per_batch(client, db):
    """Two batches — save for batch 1, no row appears for batch 2."""
    s1 = _seed_pipeline_fixture_for_korekta(db)
    mbr2_id = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, dt_utworzenia) "
        "VALUES ('TESTPROD2', 1, 'active', datetime('now')) RETURNING mbr_id"
    ).fetchone()["mbr_id"]
    ebr2_id = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, typ) "
        "VALUES (?, 'B-KOR-2', '2/KOR', datetime('now'), 'szarza') "
        "RETURNING ebr_id",
        (mbr2_id,),
    ).fetchone()["ebr_id"]
    from mbr.pipeline.models import create_sesja
    sesja2_id = create_sesja(db, ebr2_id, s1["etap_id"], runda=1, laborant="lab1")
    db.commit()

    client.put(
        f"/api/pipeline/lab/ebr/{s1['ebr_id']}/korekta",
        json={"etap_id": s1["etap_id"], "substancja": "Perhydrol 34%",
              "ilosc": 42.0, "ilosc_wyliczona": 40.0},
    )
    b1 = db.execute(
        "SELECT ilosc FROM ebr_korekta_v2 WHERE sesja_id=?", (s1["sesja_id"],)
    ).fetchone()
    b2 = db.execute(
        "SELECT ilosc FROM ebr_korekta_v2 WHERE sesja_id=?", (sesja2_id,)
    ).fetchone()
    assert b1 is not None
    assert b1["ilosc"] == 42.0
    assert b2 is None


def test_lab_start_sesja_is_idempotent_when_session_already_open(client, db):
    """Calling /etap/<id>/start on a stage whose session is already in
    'w_trakcie' or 'nierozpoczety' must return the same sesja_id with 200.
    showPipelineStage() relies on this to safely pre-start sessions on every
    sidebar switch without spawning duplicate sessions."""
    s = _seed_pipeline_fixture_for_korekta(db)
    batch_id = s["ebr_id"]
    etap_id = s["etap_id"]
    r1 = client.post(f"/api/pipeline/lab/ebr/{batch_id}/etap/{etap_id}/start")
    # Fixture pre-creates an open session, so first /start hits the existing
    # branch (200). A fresh-session test (201) is covered in
    # test_pipeline_routes.py::test_start_sesja — this test specifically
    # pins the idempotent-on-already-open invariant.
    assert r1.status_code == 200
    sid = r1.get_json()["sesja_id"]
    r2 = client.post(f"/api/pipeline/lab/ebr/{batch_id}/etap/{etap_id}/start")
    assert r2.status_code == 200
    assert r2.get_json()["sesja_id"] == sid
    db.execute(
        "UPDATE ebr_etap_sesja SET status='w_trakcie' WHERE id=?", (sid,)
    )
    db.commit()
    r3 = client.post(f"/api/pipeline/lab/ebr/{batch_id}/etap/{etap_id}/start")
    assert r3.status_code == 200
    assert r3.get_json()["sesja_id"] == sid
