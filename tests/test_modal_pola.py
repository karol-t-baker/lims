"""Modal create EBR with dynamic produkt_pola values.

Posts the existing form-encoded ``/laborant/szarze/new`` route with
``pola[<id>]`` keys and verifies they are persisted via the DAO.
"""
import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables
from mbr.shared import produkt_pola as pp


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (9001, 'T', 'U', 'TU_m', 'TU_m', 1)"
    )
    conn.execute(
        "INSERT INTO produkty (id, nazwa, kod, aktywny) VALUES (9001, 'Monamid_KO_m', 'MKO_m', 1)"
    )
    conn.execute(
        "INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, etapy_json, "
        "parametry_lab, utworzony_przez, dt_utworzenia) "
        "VALUES (9001, 'Monamid_KO_m', 1, 'active', '[]', '{}', 'tester', '2026-05-02')"
    )
    conn.commit()
    yield conn
    conn.close()


def _client(monkeypatch, db, rola="lab"):
    import mbr.db
    import mbr.laborant.routes
    import mbr.produkt_pola.routes

    @contextmanager
    def fake():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake)
    monkeypatch.setattr(mbr.produkt_pola.routes, "db_session", fake)
    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as s:
        s["user"] = {"login": "TU_m", "rola": rola, "imie_nazwisko": None}
        s["shift_workers"] = [9001]
    return c


def test_create_ebr_with_pola_persists_values(monkeypatch, db):
    pid = pp.create_pole(db, {
        "scope": "produkt", "scope_id": 9001, "kod": "nr_zam",
        "label_pl": "Nr", "typ_danych": "text", "miejsca": ["modal"],
    }, user_id=9001)
    db.commit()
    c = _client(monkeypatch, db)
    r = c.post(
        "/laborant/szarze/new",
        data={
            "produkt": "Monamid_KO_m",
            "nr_partii": "100m",
            "typ": "szarza",
            "wielkosc_kg": "1000",
            f"pola[{pid}]": "ZAM/123",
        },
        follow_redirects=False,
    )
    # Form post → 302 redirect on success
    assert r.status_code in (200, 302), r.data
    ebr_row = db.execute(
        "SELECT ebr_id FROM ebr_batches WHERE nr_partii=?", ("100m",)
    ).fetchone()
    assert ebr_row is not None
    ebr_id = ebr_row["ebr_id"]
    row = db.execute(
        "SELECT wartosc FROM ebr_pola_wartosci WHERE ebr_id=? AND pole_id=?",
        (ebr_id, pid),
    ).fetchone()
    assert row is not None
    assert row["wartosc"] == "ZAM/123"


def test_create_ebr_skips_empty_pola(monkeypatch, db):
    pid = pp.create_pole(db, {
        "scope": "produkt", "scope_id": 9001, "kod": "nr_zam",
        "label_pl": "Nr", "typ_danych": "text", "miejsca": ["modal"],
    }, user_id=9001)
    db.commit()
    c = _client(monkeypatch, db)
    r = c.post(
        "/laborant/szarze/new",
        data={
            "produkt": "Monamid_KO_m",
            "nr_partii": "101m",
            "typ": "szarza",
            "wielkosc_kg": "1000",
            f"pola[{pid}]": "",
        },
        follow_redirects=False,
    )
    assert r.status_code in (200, 302)
    ebr_row = db.execute(
        "SELECT ebr_id FROM ebr_batches WHERE nr_partii=?", ("101m",)
    ).fetchone()
    assert ebr_row is not None
    ebr_id = ebr_row["ebr_id"]
    row = db.execute(
        "SELECT wartosc FROM ebr_pola_wartosci WHERE ebr_id=? AND pole_id=?",
        (ebr_id, pid),
    ).fetchone()
    # Empty values are skipped → no row written
    assert row is None
