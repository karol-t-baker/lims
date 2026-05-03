"""HTTP API tests for /api/produkt-pola."""
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
        "VALUES (9001, 'T', 'U', 'TU_a', 'TU_a', 1)"
    )
    conn.execute(
        "INSERT INTO produkty (id, nazwa, kod, aktywny) "
        "VALUES (9001, 'Monamid_KO_a', 'MKO_a', 1)"
    )
    conn.commit()
    yield conn
    conn.close()


def _client(monkeypatch, db, rola="admin"):
    import mbr.db
    import mbr.produkt_pola.routes

    @contextmanager
    def fake():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake)
    monkeypatch.setattr(mbr.produkt_pola.routes, "db_session", fake)
    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as s:
        s["user"] = {"login": "TU_a", "rola": rola, "imie_nazwisko": None}
        s["shift_workers"] = [9001]
    return c


def test_get_produkt_pola_empty(monkeypatch, db):
    c = _client(monkeypatch, db)
    r = c.get("/api/produkt-pola?scope=produkt&scope_id=9001")
    assert r.status_code == 200
    assert r.json == {"pola": []}


def test_get_produkt_pola_returns_active_fields(monkeypatch, db):
    pp.create_pole(db, {
        "scope": "produkt", "scope_id": 9001, "kod": "k1",
        "label_pl": "L1", "typ_danych": "text", "miejsca": ["modal"],
    }, user_id=9001)
    db.commit()
    c = _client(monkeypatch, db)
    r = c.get("/api/produkt-pola?scope=produkt&scope_id=9001")
    assert r.status_code == 200
    pola = r.json["pola"]
    assert len(pola) == 1
    assert pola[0]["kod"] == "k1"
    assert pola[0]["miejsca"] == ["modal"]


def test_get_ebr_pola_returns_values(monkeypatch, db):
    db.execute(
        "INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, etapy_json, "
        "parametry_lab, utworzony_przez, dt_utworzenia) "
        "VALUES (9001, 'Monamid_KO_a', 1, 'active', '[]', '{}', 'tester', '2026-05-02')"
    )
    db.execute(
        "INSERT INTO ebr_batches (ebr_id, batch_id, mbr_id, nr_partii, dt_start, status) "
        "VALUES (9001, 'B1_a', 9001, '001_a', '2026-05-02', 'open')"
    )
    pid = pp.create_pole(db, {
        "scope": "produkt", "scope_id": 9001, "kod": "nr_zam",
        "label_pl": "Nr", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=9001)
    pp.set_wartosc(db, 9001, pid, "ZAM/1", user_id=9001)
    db.commit()
    c = _client(monkeypatch, db, rola="lab")
    r = c.get("/api/ebr/9001/pola")
    assert r.status_code == 200
    assert r.json["wartosci"] == {"nr_zam": "ZAM/1"}
