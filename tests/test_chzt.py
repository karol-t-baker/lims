"""Tests for mbr.chzt — sessions, pomiary, autosave, history."""

import json as _json
import sqlite3
import pytest
from contextlib import contextmanager
from datetime import datetime, date

from mbr.models import init_mbr_tables
from mbr.chzt.models import init_chzt_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    init_chzt_tables(conn)
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (1, 'Jan', 'Kowalski', 'JK', 'JK', 1)"
    )
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (2, 'Anna', 'Nowak', 'AN', 'AN', 1)"
    )
    conn.commit()
    yield conn
    conn.close()


def test_init_chzt_tables_creates_sesje(db):
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chzt_sesje'"
    ).fetchone()
    assert row is not None


def test_init_chzt_tables_creates_pomiary(db):
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chzt_pomiary'"
    ).fetchone()
    assert row is not None


def test_init_chzt_tables_data_unique(db):
    db.execute(
        "INSERT INTO chzt_sesje (data, n_kontenery, created_at, created_by) "
        "VALUES ('2026-04-18', 8, '2026-04-18T10:00:00', 1)"
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO chzt_sesje (data, n_kontenery, created_at, created_by) "
            "VALUES ('2026-04-18', 8, '2026-04-18T11:00:00', 1)"
        )


def test_init_chzt_tables_pomiar_unique_per_session(db):
    db.execute(
        "INSERT INTO chzt_sesje (id, data, n_kontenery, created_at, created_by) "
        "VALUES (1, '2026-04-18', 8, '2026-04-18T10:00:00', 1)"
    )
    db.execute(
        "INSERT INTO chzt_pomiary (sesja_id, punkt_nazwa, kolejnosc, updated_at) "
        "VALUES (1, 'hala', 1, '2026-04-18T10:00:00')"
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO chzt_pomiary (sesja_id, punkt_nazwa, kolejnosc, updated_at) "
            "VALUES (1, 'hala', 2, '2026-04-18T10:05:00')"
        )


from mbr.chzt.models import build_punkty_names


def test_build_punkty_names_n0():
    assert build_punkty_names(0) == ["hala", "rura", "szambiarka"]


def test_build_punkty_names_n8():
    names = build_punkty_names(8)
    assert names[0] == "hala"
    assert names[1] == "rura"
    assert names[2:10] == [f"kontener {i}" for i in range(1, 9)]
    assert names[-1] == "szambiarka"
    assert len(names) == 11


from mbr.chzt.models import get_or_create_session, get_session_with_pomiary


def test_get_or_create_session_creates_fresh(db):
    session_id, created = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=8)
    db.commit()
    assert created is True
    assert isinstance(session_id, int)

    pomiary = db.execute(
        "SELECT punkt_nazwa, kolejnosc FROM chzt_pomiary WHERE sesja_id=? ORDER BY kolejnosc",
        (session_id,),
    ).fetchall()
    assert len(pomiary) == 11
    assert pomiary[0]["punkt_nazwa"] == "hala"
    assert pomiary[0]["kolejnosc"] == 1
    assert pomiary[-1]["punkt_nazwa"] == "szambiarka"
    assert pomiary[-1]["kolejnosc"] == 11


def test_get_or_create_session_idempotent(db):
    sid1, c1 = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=8)
    db.commit()
    sid2, c2 = get_or_create_session(db, "2026-04-18", created_by=2, n_kontenery=5)
    db.commit()
    assert sid1 == sid2
    assert c1 is True
    assert c2 is False
    row = db.execute("SELECT n_kontenery FROM chzt_sesje WHERE id=?", (sid1,)).fetchone()
    assert row["n_kontenery"] == 8


def test_get_session_with_pomiary_shape(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=2)
    db.commit()
    session = get_session_with_pomiary(db, sid)
    assert session["id"] == sid
    assert session["data"] == "2026-04-18"
    assert session["n_kontenery"] == 2
    assert session["finalized_at"] is None
    assert len(session["punkty"]) == 5
    hala = session["punkty"][0]
    assert hala["punkt_nazwa"] == "hala"
    assert hala["ph"] is None
    assert hala["srednia"] is None


def test_get_session_with_pomiary_returns_none_when_missing(db):
    assert get_session_with_pomiary(db, 99999) is None


@pytest.fixture
def client(monkeypatch, db):
    """Flask test client with session user + shift workers seeded."""
    import mbr.db
    import mbr.chzt.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.chzt.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = {"login": "jk", "rola": "lab", "imie_nazwisko": "Jan Kowalski"}
        sess["shift_workers"] = [1]
    return c


@pytest.fixture
def admin_client(monkeypatch, db):
    import mbr.db
    import mbr.chzt.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.chzt.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = {"login": "admin", "rola": "admin", "imie_nazwisko": "Admin"}
    return c


def test_session_today_creates_and_returns(client, db):
    resp = client.get("/api/chzt/session/today")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["session"]["data"] == date.today().isoformat()
    assert data["session"]["finalized_at"] is None
    assert len(data["session"]["punkty"]) == 11


def test_session_today_idempotent(client, db):
    r1 = client.get("/api/chzt/session/today").get_json()
    r2 = client.get("/api/chzt/session/today").get_json()
    assert r1["session"]["id"] == r2["session"]["id"]


def test_session_today_logs_created_audit(client, db):
    client.get("/api/chzt/session/today")
    rows = db.execute(
        "SELECT event_type FROM audit_log WHERE event_type='chzt.session.created'"
    ).fetchall()
    assert len(rows) == 1


def test_session_today_logs_created_audit_only_once(client, db):
    client.get("/api/chzt/session/today")
    client.get("/api/chzt/session/today")
    rows = db.execute(
        "SELECT event_type FROM audit_log WHERE event_type='chzt.session.created'"
    ).fetchall()
    assert len(rows) == 1


from mbr.chzt.models import compute_srednia


def test_compute_srednia_none_when_lt_2():
    assert compute_srednia({"p1": 10, "p2": None, "p3": None, "p4": None, "p5": None}) is None
    assert compute_srednia({"p1": None, "p2": None, "p3": None, "p4": None, "p5": None}) is None


def test_compute_srednia_average_of_nonnull():
    assert compute_srednia({"p1": 10, "p2": 20, "p3": None, "p4": None, "p5": None}) == 15.0
    assert compute_srednia({"p1": 10, "p2": 20, "p3": 30, "p4": 40, "p5": 50}) == 30.0


from mbr.chzt.models import get_pomiar, update_pomiar


def test_get_pomiar_returns_row(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=2)
    db.commit()
    row = db.execute("SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='hala'", (sid,)).fetchone()
    p = get_pomiar(db, row["id"])
    assert p["punkt_nazwa"] == "hala"
    assert p["ph"] is None
    assert p["sesja_id"] == sid


def test_get_pomiar_returns_none_for_missing(db):
    assert get_pomiar(db, 99999) is None


def test_update_pomiar_writes_fields_and_srednia(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=2)
    db.commit()
    pid = db.execute("SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='hala'", (sid,)).fetchone()["id"]
    update_pomiar(db, pid, {"ph": 10, "p1": 100, "p2": 200, "p3": None, "p4": None, "p5": None}, updated_by=1)
    db.commit()
    row = db.execute("SELECT ph, p1, p2, srednia FROM chzt_pomiary WHERE id=?", (pid,)).fetchone()
    assert row["ph"] == 10
    assert row["p1"] == 100
    assert row["p2"] == 200
    assert row["srednia"] == 150.0


def test_update_pomiar_clears_srednia_if_lt_2(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=2)
    db.commit()
    pid = db.execute("SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='hala'", (sid,)).fetchone()["id"]
    update_pomiar(db, pid, {"ph": 10, "p1": 100, "p2": None, "p3": None, "p4": None, "p5": None}, updated_by=1)
    db.commit()
    row = db.execute("SELECT srednia FROM chzt_pomiary WHERE id=?", (pid,)).fetchone()
    assert row["srednia"] is None


def _get_today_pomiar_id(client, db, punkt="hala"):
    resp = client.get("/api/chzt/session/today")
    session_payload = resp.get_json()["session"]
    for p in session_payload["punkty"]:
        if p["punkt_nazwa"] == punkt:
            return p["id"]
    raise AssertionError(f"punkt {punkt} not found")


def test_put_pomiar_updates_row(client, db):
    pid = _get_today_pomiar_id(client, db, "hala")
    resp = client.put(f"/api/chzt/pomiar/{pid}", json={
        "ph": 10, "p1": 25000, "p2": 26000, "p3": None, "p4": None, "p5": None
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["pomiar"]["ph"] == 10
    assert data["pomiar"]["srednia"] == 25500.0
    assert data["pomiar"]["updated_at"] is not None


def test_put_pomiar_logs_audit_with_diff(client, db):
    pid = _get_today_pomiar_id(client, db, "hala")
    client.put(f"/api/chzt/pomiar/{pid}", json={
        "ph": 10, "p1": 25000, "p2": 26000, "p3": None, "p4": None, "p5": None
    })
    rows = db.execute(
        "SELECT event_type, diff_json, entity_id FROM audit_log "
        "WHERE event_type='chzt.pomiar.updated'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["entity_id"] == pid
    diff = _json.loads(rows[0]["diff_json"])
    fields = {d["pole"] for d in diff}
    assert "ph" in fields
    assert "p1" in fields
    assert "p2" in fields


def test_put_pomiar_no_audit_on_noop(client, db):
    pid = _get_today_pomiar_id(client, db, "hala")
    client.put(f"/api/chzt/pomiar/{pid}", json={
        "ph": 10, "p1": 25000, "p2": 26000, "p3": None, "p4": None, "p5": None
    })
    client.put(f"/api/chzt/pomiar/{pid}", json={
        "ph": 10, "p1": 25000, "p2": 26000, "p3": None, "p4": None, "p5": None
    })
    rows = db.execute(
        "SELECT event_type FROM audit_log WHERE event_type='chzt.pomiar.updated'"
    ).fetchall()
    assert len(rows) == 1


def test_put_pomiar_404_for_missing(client, db):
    resp = client.put("/api/chzt/pomiar/99999", json={
        "ph": 10, "p1": 1, "p2": 2, "p3": None, "p4": None, "p5": None
    })
    assert resp.status_code == 404
