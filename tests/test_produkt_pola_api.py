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


def test_post_produkt_pola_create(monkeypatch, db):
    c = _client(monkeypatch, db)
    r = c.post("/api/produkt-pola", json={
        "scope": "produkt", "scope_id": 9001, "kod": "nr_zam",
        "label_pl": "Nr zamowienia", "typ_danych": "text",
        "miejsca": ["modal", "hero", "ukonczone"],
        "kolejnosc": 10,
    })
    assert r.status_code == 201, r.json
    pid = r.json["pole_id"]
    row = db.execute("SELECT * FROM produkt_pola WHERE id=?", (pid,)).fetchone()
    assert row["kod"] == "nr_zam"


def test_post_produkt_pola_invalid_kod(monkeypatch, db):
    c = _client(monkeypatch, db)
    r = c.post("/api/produkt-pola", json={
        "scope": "produkt", "scope_id": 9001,
        "kod": "Bad Kod!", "label_pl": "L", "typ_danych": "text", "miejsca": [],
    })
    assert r.status_code == 400
    assert "kod" in (r.json.get("error") or "")


def test_post_produkt_pola_duplicate_409(monkeypatch, db):
    pp.create_pole(db, {
        "scope": "produkt", "scope_id": 9001, "kod": "dupl",
        "label_pl": "L", "typ_danych": "text", "miejsca": [],
    }, user_id=9001)
    db.commit()
    c = _client(monkeypatch, db)
    r = c.post("/api/produkt-pola", json={
        "scope": "produkt", "scope_id": 9001, "kod": "dupl",
        "label_pl": "L2", "typ_danych": "text", "miejsca": [],
    })
    assert r.status_code == 409


def test_post_produkt_pola_requires_admin_or_technolog(monkeypatch, db):
    c = _client(monkeypatch, db, rola="lab")
    r = c.post("/api/produkt-pola", json={
        "scope": "produkt", "scope_id": 9001, "kod": "k", "label_pl": "L",
        "typ_danych": "text", "miejsca": [],
    })
    assert r.status_code == 403


def test_put_produkt_pola_update_label(monkeypatch, db):
    pid = pp.create_pole(db, {
        "scope": "produkt", "scope_id": 9001, "kod": "k",
        "label_pl": "Stary", "typ_danych": "text", "miejsca": [],
    }, user_id=9001)
    db.commit()
    c = _client(monkeypatch, db)
    r = c.put(f"/api/produkt-pola/{pid}", json={"label_pl": "Nowy"})
    assert r.status_code == 200
    row = db.execute(
        "SELECT label_pl FROM produkt_pola WHERE id=?", (pid,)
    ).fetchone()
    assert row["label_pl"] == "Nowy"


def test_put_produkt_pola_kod_immutable(monkeypatch, db):
    pid = pp.create_pole(db, {
        "scope": "produkt", "scope_id": 9001, "kod": "k",
        "label_pl": "L", "typ_danych": "text", "miejsca": [],
    }, user_id=9001)
    db.commit()
    c = _client(monkeypatch, db)
    r = c.put(f"/api/produkt-pola/{pid}", json={"kod": "inny"})
    assert r.status_code == 400


def test_delete_produkt_pola_soft(monkeypatch, db):
    pid = pp.create_pole(db, {
        "scope": "produkt", "scope_id": 9001, "kod": "k",
        "label_pl": "L", "typ_danych": "text", "miejsca": [],
    }, user_id=9001)
    db.commit()
    c = _client(monkeypatch, db)
    r = c.delete(f"/api/produkt-pola/{pid}")
    assert r.status_code == 200
    row = db.execute(
        "SELECT aktywne FROM produkt_pola WHERE id=?", (pid,)
    ).fetchone()
    assert row["aktywne"] == 0


@pytest.fixture
def db_with_ebr(db):
    db.execute(
        "INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, etapy_json, "
        "parametry_lab, utworzony_przez, dt_utworzenia) "
        "VALUES (9001, 'Monamid_KO_a', 1, 'active', '[]', '{}', 'tester', '2026-05-02')"
    )
    db.execute(
        "INSERT INTO ebr_batches (ebr_id, batch_id, mbr_id, nr_partii, dt_start, status) "
        "VALUES (9001, 'B1_a', 9001, '001_a', '2026-05-02', 'open')"
    )
    db.commit()
    return db


def test_put_ebr_pola_value(monkeypatch, db_with_ebr):
    pid = pp.create_pole(db_with_ebr, {
        "scope": "produkt", "scope_id": 9001, "kod": "nr_zam",
        "label_pl": "Nr", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=9001)
    db_with_ebr.commit()
    c = _client(monkeypatch, db_with_ebr, rola="lab")
    r = c.put(f"/api/ebr/9001/pola/{pid}", json={"wartosc": "ZAM/1"})
    assert r.status_code == 200
    row = db_with_ebr.execute(
        "SELECT wartosc FROM ebr_pola_wartosci WHERE ebr_id=9001 AND pole_id=?",
        (pid,),
    ).fetchone()
    assert row["wartosc"] == "ZAM/1"


def test_put_ebr_pola_clear_to_null(monkeypatch, db_with_ebr):
    pid = pp.create_pole(db_with_ebr, {
        "scope": "produkt", "scope_id": 9001, "kod": "k",
        "label_pl": "L", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=9001)
    pp.set_wartosc(db_with_ebr, 9001, pid, "X", user_id=9001)
    db_with_ebr.commit()
    c = _client(monkeypatch, db_with_ebr, rola="lab")
    r = c.put(f"/api/ebr/9001/pola/{pid}", json={"wartosc": None})
    assert r.status_code == 200
    row = db_with_ebr.execute(
        "SELECT wartosc FROM ebr_pola_wartosci WHERE ebr_id=9001 AND pole_id=?",
        (pid,),
    ).fetchone()
    assert row["wartosc"] is None


def test_put_ebr_pola_invalid_number(monkeypatch, db_with_ebr):
    pid = pp.create_pole(db_with_ebr, {
        "scope": "produkt", "scope_id": 9001, "kod": "i",
        "label_pl": "I", "typ_danych": "number", "miejsca": ["hero"],
    }, user_id=9001)
    db_with_ebr.commit()
    c = _client(monkeypatch, db_with_ebr, rola="lab")
    r = c.put(f"/api/ebr/9001/pola/{pid}", json={"wartosc": "abc"})
    assert r.status_code == 400


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
