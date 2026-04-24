"""Tests for mbr.chzt — sessions, pomiary, autosave, history."""

import json as _json
import sqlite3
import pytest
from contextlib import contextmanager
from datetime import datetime, date

from mbr.models import init_mbr_tables
from mbr.chzt.models import init_chzt_tables, create_session as _create_session


def get_or_create_session(db, data_iso: str, *, created_by: int, n_kontenery: int = 8):
    """Test-only shim replacing the old API. Creates a session if none open,
    returns (session_id, created_bool)."""
    existing = db.execute(
        "SELECT id FROM chzt_sesje WHERE finalized_at IS NULL LIMIT 1"
    ).fetchone()
    if existing:
        return existing["id"], False
    sid = _create_session(db, created_by=created_by, n_kontenery=n_kontenery)
    return sid, True


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


from mbr.chzt.models import get_session_with_pomiary



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



from mbr.chzt.models import compute_srednia


def test_compute_srednia_none_when_lt_2():
    assert compute_srednia({"p1": 10, "p2": None, "p3": None, "p4": None, "p5": None}) is None
    assert compute_srednia({"p1": None, "p2": None, "p3": None, "p4": None, "p5": None}) is None


def test_compute_srednia_average_of_nonnull():
    assert compute_srednia({"p1": 10, "p2": 20, "p3": None, "p4": None, "p5": None}) == 15.0
    assert compute_srednia({"p1": 10, "p2": 20, "p3": 30, "p4": 40, "p5": 50}) == 30.0


def test_compute_srednia_exactly_2_values():
    """Boundary: threshold is >= 2, so 2 non-null must compute."""
    assert compute_srednia({"p1": 100, "p2": 200, "p3": None, "p4": None, "p5": None}) == 150.0


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
    active = client.get("/api/chzt/session/active").get_json()["session"]
    if active is None:
        active = client.post("/api/chzt/session/new", json={"n_kontenery": 8}).get_json()["session"]
    for p in active["punkty"]:
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


from mbr.chzt.models import resize_kontenery


def test_resize_kontenery_up_adds_rows(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=2)
    db.commit()
    resize_kontenery(db, sid, new_n=5)
    db.commit()
    rows = db.execute(
        "SELECT punkt_nazwa, kolejnosc FROM chzt_pomiary WHERE sesja_id=? ORDER BY kolejnosc",
        (sid,),
    ).fetchall()
    names = [r["punkt_nazwa"] for r in rows]
    assert names == ["hala", "rura", "kontener 1", "kontener 2", "kontener 3",
                     "kontener 4", "kontener 5", "szambiarka"]
    assert rows[-1]["kolejnosc"] == 8


def test_resize_kontenery_down_empty_deletes(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=5)
    db.commit()
    resize_kontenery(db, sid, new_n=2)
    db.commit()
    names = [r["punkt_nazwa"] for r in db.execute(
        "SELECT punkt_nazwa FROM chzt_pomiary WHERE sesja_id=? ORDER BY kolejnosc", (sid,)
    ).fetchall()]
    assert "kontener 3" not in names
    assert "kontener 4" not in names
    assert "kontener 5" not in names
    assert names[-1] == "szambiarka"


def test_resize_kontenery_down_with_data_raises(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=5)
    db.commit()
    db.execute(
        "UPDATE chzt_pomiary SET ph=7 WHERE sesja_id=? AND punkt_nazwa='kontener 4'",
        (sid,),
    )
    db.commit()
    with pytest.raises(ValueError) as exc:
        resize_kontenery(db, sid, new_n=2)
    assert "kontener 4" in str(exc.value)


def test_resize_kontenery_updates_session_n(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=2)
    db.commit()
    resize_kontenery(db, sid, new_n=7)
    db.commit()
    n = db.execute("SELECT n_kontenery FROM chzt_sesje WHERE id=?", (sid,)).fetchone()["n_kontenery"]
    assert n == 7


def test_patch_session_n_kontenery_up(client, db):
    r0 = client.post("/api/chzt/session/new", json={"n_kontenery": 8}).get_json()
    sid = r0["session"]["id"]
    resp = client.patch(f"/api/chzt/session/{sid}", json={"n_kontenery": 10})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["session"]["n_kontenery"] == 10
    names = [p["punkt_nazwa"] for p in data["session"]["punkty"]]
    assert "kontener 10" in names


def test_patch_session_n_kontenery_down_blocked(client, db):
    r0 = client.post("/api/chzt/session/new", json={"n_kontenery": 8}).get_json()
    sid = r0["session"]["id"]
    k5_pid = None
    for p in r0["session"]["punkty"]:
        if p["punkt_nazwa"] == "kontener 5":
            k5_pid = p["id"]
    client.put(f"/api/chzt/pomiar/{k5_pid}", json={
        "ph": 10, "p1": 100, "p2": 200, "p3": None, "p4": None, "p5": None
    })
    resp = client.patch(f"/api/chzt/session/{sid}", json={"n_kontenery": 3})
    assert resp.status_code == 409
    body = resp.get_json()
    assert "kontener 5" in body["error"]


def test_patch_session_logs_audit(client, db):
    r0 = client.post("/api/chzt/session/new", json={"n_kontenery": 8}).get_json()
    sid = r0["session"]["id"]
    client.patch(f"/api/chzt/session/{sid}", json={"n_kontenery": 10})
    rows = db.execute(
        "SELECT event_type, diff_json FROM audit_log "
        "WHERE event_type='chzt.session.n_kontenery_changed'"
    ).fetchall()
    assert len(rows) == 1
    diff = _json.loads(rows[0]["diff_json"])
    assert diff[0]["pole"] == "n_kontenery"
    assert diff[0]["stara"] == 8
    assert diff[0]["nowa"] == 10


from mbr.chzt.models import validate_for_finalize, finalize_session, unfinalize_session


def test_validate_for_finalize_empty_fails(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=1)
    db.commit()
    errors = validate_for_finalize(db, sid)
    assert len(errors) == 4  # hala, rura, kontener 1, szambiarka all missing
    assert any(e["punkt_nazwa"] == "hala" and "ph" in e["reason"] for e in errors)


def test_validate_for_finalize_passes_when_complete(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=0)
    db.commit()
    for punkt in ("hala", "rura", "szambiarka"):
        pid = db.execute(
            "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa=?",
            (sid, punkt),
        ).fetchone()["id"]
        update_pomiar(db, pid, {"ph": 10, "p1": 1, "p2": 2, "p3": None, "p4": None, "p5": None}, updated_by=1)
    db.commit()
    errors = validate_for_finalize(db, sid)
    assert errors == []


def test_validate_for_finalize_flags_less_than_2(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=0)
    db.commit()
    for punkt in ("hala", "rura"):
        pid = db.execute(
            "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa=?",
            (sid, punkt),
        ).fetchone()["id"]
        update_pomiar(db, pid, {"ph": 10, "p1": 1, "p2": 2, "p3": None, "p4": None, "p5": None}, updated_by=1)
    szam_id = db.execute(
        "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='szambiarka'", (sid,)
    ).fetchone()["id"]
    update_pomiar(db, szam_id, {"ph": 10, "p1": 1, "p2": None, "p3": None, "p4": None, "p5": None}, updated_by=1)
    db.commit()
    errors = validate_for_finalize(db, sid)
    assert len(errors) == 1
    assert errors[0]["punkt_nazwa"] == "szambiarka"
    assert "pomiary" in errors[0]["reason"]


def _fill_all_today(client, db, ph=10, p1=100, p2=200):
    # Ensure active session (create one if none)
    active = client.get("/api/chzt/session/active").get_json()["session"]
    if active is None:
        active = client.post("/api/chzt/session/new", json={"n_kontenery": 8}).get_json()["session"]
    sid = active["id"]
    for p in active["punkty"]:
        client.put(f"/api/chzt/pomiar/{p['id']}", json={
            "ph": ph, "p1": p1, "p2": p2, "p3": None, "p4": None, "p5": None
        })
    return sid


def test_finalize_empty_returns_400_with_errors(client, db):
    r = client.post("/api/chzt/session/new", json={"n_kontenery": 8}).get_json()
    sid = r["session"]["id"]
    resp = client.post(f"/api/chzt/session/{sid}/finalize")
    assert resp.status_code == 400
    body = resp.get_json()
    assert "errors" in body
    assert len(body["errors"]) > 0


def test_finalize_valid_sets_marker(client, db):
    sid = _fill_all_today(client, db)
    resp = client.post(f"/api/chzt/session/{sid}/finalize")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["session"]["finalized_at"] is not None
    assert body["session"]["finalized_by"] == 1


def test_finalize_logs_audit(client, db):
    sid = _fill_all_today(client, db)
    client.post(f"/api/chzt/session/{sid}/finalize")
    rows = db.execute(
        "SELECT event_type FROM audit_log WHERE event_type='chzt.session.finalized'"
    ).fetchall()
    assert len(rows) == 1


def test_finalize_allows_edit_after(client, db):
    sid = _fill_all_today(client, db)
    client.post(f"/api/chzt/session/{sid}/finalize")
    pid = _get_today_pomiar_id(client, db, "hala")
    client.put(f"/api/chzt/pomiar/{pid}", json={
        "ph": 11, "p1": 100, "p2": 200, "p3": None, "p4": None, "p5": None
    })
    row = db.execute(
        "SELECT finalized_at FROM chzt_sesje WHERE id=?", (sid,)
    ).fetchone()
    assert row["finalized_at"] is not None


def test_unfinalize_lab_forbidden(client, db):
    sid = _fill_all_today(client, db)
    client.post(f"/api/chzt/session/{sid}/finalize")
    resp = client.post(f"/api/chzt/session/{sid}/unfinalize")
    assert resp.status_code == 403


def test_unfinalize_admin_ok(admin_client, client, db):
    sid = _fill_all_today(client, db)
    client.post(f"/api/chzt/session/{sid}/finalize")
    resp = admin_client.post(f"/api/chzt/session/{sid}/unfinalize")
    assert resp.status_code == 200
    row = db.execute(
        "SELECT finalized_at FROM chzt_sesje WHERE id=?", (sid,)
    ).fetchone()
    assert row["finalized_at"] is None


from mbr.chzt.models import list_sessions_paginated


def test_list_sessions_paginated_desc_order(db):
    for dt in ["2026-04-16T08:00:00", "2026-04-18T08:00:00", "2026-04-17T08:00:00"]:
        db.execute(
            "INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at, created_by) "
            "VALUES (?, 8, ?, 1)", (dt, dt)
        )
    db.commit()
    page = list_sessions_paginated(db, page=1, per_page=10)
    dts = [s["dt_start"] for s in page["sesje"]]
    assert dts[0].startswith("2026-04-18")
    assert dts[1].startswith("2026-04-17")
    assert dts[2].startswith("2026-04-16")
    assert page["total"] == 3
    assert page["page"] == 1
    assert page["pages"] == 1


def test_list_sessions_paginated_splits_pages(db):
    for d in ["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04", "2026-04-05",
              "2026-04-06", "2026-04-07", "2026-04-08", "2026-04-09", "2026-04-10",
              "2026-04-11", "2026-04-12"]:
        dt = d + "T08:00:00"
        db.execute(
            "INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at, created_by) "
            "VALUES (?, 0, ?, 1)", (dt, dt)
        )
    db.commit()
    page1 = list_sessions_paginated(db, page=1, per_page=10)
    page2 = list_sessions_paginated(db, page=2, per_page=10)
    assert len(page1["sesje"]) == 10
    assert len(page2["sesje"]) == 2
    assert page1["pages"] == 2
    assert page2["page"] == 2


def test_list_sessions_paginated_returns_szambiarka_fields(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=1)
    db.commit()
    pid_hala = db.execute(
        "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='hala'", (sid,)
    ).fetchone()["id"]
    pid_k1 = db.execute(
        "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='kontener 1'", (sid,)
    ).fetchone()["id"]
    pid_sz = db.execute(
        "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='szambiarka'", (sid,)
    ).fetchone()["id"]
    update_pomiar(db, pid_hala, {"ph": 9, "p1": 20000, "p2": 22000, "p3": None, "p4": None, "p5": None}, updated_by=1)
    update_pomiar(db, pid_k1,   {"ph": 11, "p1": 45000, "p2": 44000, "p3": None, "p4": None, "p5": None}, updated_by=1)
    update_pomiar(db, pid_sz, {
        "ph": 10, "p1": 30000, "p2": 31000, "p3": None, "p4": None, "p5": None,
        "ext_ph": 11, "ext_chzt": 28000, "waga_kg": 16500,
        "uwagi": "Po wyjeździe dodano 5L NaOH",
    }, updated_by=1)
    db.commit()
    page = list_sessions_paginated(db, page=1, per_page=10)
    s = page["sesje"][0]
    # szambiarka row fields
    assert s["sz_chzt"] == 30500       # avg of 30000, 31000
    assert s["sz_ph"] == 10
    assert s["sz_ext_chzt"] == 28000
    assert s["sz_ext_ph"] == 11
    assert s["sz_waga"] == 16500
    assert s["sz_uwagi"] == "Po wyjeździe dodano 5L NaOH"
    # pH breach count: hala=9 OK, k1=11 > 10 ✓, szambiarka=10 NOT over (strict >)
    assert s["over_ph_count"] == 1
    # n_kontenery passthrough
    assert s["n_kontenery"] == 1


def test_list_sessions_paginated_empty_szambiarka_returns_nulls(db):
    """Session with no measurements on the szambiarka punkt → sz_* fields are None
    and over_ph_count is 0. Template renders '—' for None."""
    sid, _ = get_or_create_session(db, "2026-04-19", created_by=1, n_kontenery=0)
    db.commit()
    page = list_sessions_paginated(db, page=1, per_page=10)
    s = page["sesje"][0]
    assert s["sz_chzt"] is None
    assert s["sz_ph"] is None
    assert s["sz_ext_chzt"] is None
    assert s["sz_ext_ph"] is None
    assert s["sz_waga"] is None
    assert s["sz_uwagi"] is None
    assert s["over_ph_count"] == 0


def test_update_pomiar_roundtrips_uwagi_and_normalizes_empty(db):
    """update_pomiar stores uwagi as a string; whitespace-only / '' → None."""
    sid, _ = get_or_create_session(db, "2026-04-20", created_by=1, n_kontenery=0)
    db.commit()
    pid_sz = db.execute(
        "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='szambiarka'", (sid,)
    ).fetchone()["id"]
    # Write
    update_pomiar(db, pid_sz, {"uwagi": "Kożuch na powierzchni"}, updated_by=1)
    db.commit()
    row = db.execute("SELECT uwagi FROM chzt_pomiary WHERE id=?", (pid_sz,)).fetchone()
    assert row["uwagi"] == "Kożuch na powierzchni"
    # Overwrite with None → NULL
    update_pomiar(db, pid_sz, {"uwagi": None}, updated_by=1)
    db.commit()
    row = db.execute("SELECT uwagi FROM chzt_pomiary WHERE id=?", (pid_sz,)).fetchone()
    assert row["uwagi"] is None


def test_get_day_finalized_returns_frame(client, db):
    sid = _fill_all_today(client, db, ph=10, p1=25000, p2=26000)
    client.post(f"/api/chzt/session/{sid}/finalize")
    today = date.today().isoformat()
    resp = client.get(f"/api/chzt/day/{today}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["dt_start"].startswith(today)
    assert body["finalized_at"] is not None
    punkty = {p["nazwa"]: p for p in body["punkty"]}
    assert punkty["hala"]["ph"] == 10
    assert punkty["hala"]["srednia"] == 25500.0


def test_get_day_draft_returns_404(client, db):
    _fill_all_today(client, db)
    today = date.today().isoformat()
    resp = client.get(f"/api/chzt/day/{today}")
    assert resp.status_code == 404


def test_get_history_paginated(client, db):
    for d in ["2026-04-10", "2026-04-11", "2026-04-12"]:
        dt = d + "T10:00:00"
        db.execute(
            "INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at, created_by) "
            "VALUES (?, 0, ?, 1)",
            (dt, dt),
        )
    db.commit()
    resp = client.get("/api/chzt/history?page=1")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total"] == 3
    assert body["sesje"][0]["dt_start"].startswith("2026-04-12")


def test_historia_page_renders(client, db):
    for d in ["2026-04-17", "2026-04-18"]:
        dt = d + "T10:00:00"
        db.execute(
            "INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at, created_by) "
            "VALUES (?, 0, ?, 1)",
            (dt, dt),
        )
    db.commit()
    resp = client.get("/chzt/historia")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "2026-04-18" in body
    assert "2026-04-17" in body


def test_get_session_with_pomiary_includes_finalized_by_name(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=0)
    db.commit()
    # Populate all required fields for finalize
    for punkt in ("hala", "rura", "szambiarka"):
        pid = db.execute(
            "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa=?",
            (sid, punkt),
        ).fetchone()["id"]
        update_pomiar(db, pid, {"ph": 10, "p1": 1, "p2": 2, "p3": None, "p4": None, "p5": None}, updated_by=1)
    finalize_session(db, sid, finalized_by=2)
    db.commit()
    session_data = get_session_with_pomiary(db, sid)
    assert session_data["finalized_by_name"] == "Anna Nowak"


def test_get_session_with_pomiary_finalized_by_name_null_when_not_finalized(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=0)
    db.commit()
    session_data = get_session_with_pomiary(db, sid)
    assert session_data["finalized_by_name"] is None


def test_patch_session_n_kontenery_rejects_over_20(client, db):
    r0 = client.post("/api/chzt/session/new", json={"n_kontenery": 8}).get_json()
    sid = r0["session"]["id"]
    resp = client.patch(f"/api/chzt/session/{sid}", json={"n_kontenery": 21})
    assert resp.status_code == 400


# ───────────────────────────────────────────────────────────────
# Migracja: stary schemat → nowy (idempotentna)
# ───────────────────────────────────────────────────────────────

def test_migration_from_old_schema_preserves_sesje_data():
    """Old schema (with `data` and UNIQUE(data)) migrates to new (dt_start)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    conn.execute("""
        CREATE TABLE chzt_sesje (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            data         TEXT NOT NULL UNIQUE,
            n_kontenery  INTEGER NOT NULL DEFAULT 8,
            created_at   TEXT NOT NULL,
            created_by   INTEGER REFERENCES workers(id),
            finalized_at TEXT,
            finalized_by INTEGER REFERENCES workers(id)
        )
    """)
    conn.execute("""
        CREATE TABLE chzt_pomiary (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            sesja_id     INTEGER NOT NULL REFERENCES chzt_sesje(id) ON DELETE CASCADE,
            punkt_nazwa  TEXT NOT NULL,
            kolejnosc    INTEGER NOT NULL,
            ph           REAL,
            p1           REAL, p2 REAL, p3 REAL, p4 REAL, p5 REAL,
            srednia      REAL,
            updated_at   TEXT NOT NULL,
            updated_by   INTEGER REFERENCES workers(id),
            UNIQUE(sesja_id, punkt_nazwa)
        )
    """)
    conn.execute(
        "INSERT INTO chzt_sesje (data, n_kontenery, created_at) "
        "VALUES ('2026-04-10', 8, '2026-04-10T10:00:00')"
    )
    conn.execute(
        "INSERT INTO chzt_pomiary (sesja_id, punkt_nazwa, kolejnosc, ph, p1, p2, updated_at) "
        "VALUES (1, 'hala', 1, 10, 20000, 22000, '2026-04-10T10:30:00')"
    )
    conn.commit()

    init_chzt_tables(conn)

    cols = {r[1] for r in conn.execute("PRAGMA table_info(chzt_sesje)").fetchall()}
    assert "dt_start" in cols
    assert "data" not in cols

    row = conn.execute("SELECT id, dt_start, n_kontenery FROM chzt_sesje").fetchone()
    assert row["id"] == 1
    assert row["dt_start"].startswith("2026-04-10")
    assert row["n_kontenery"] == 8

    pcols = {r[1] for r in conn.execute("PRAGMA table_info(chzt_pomiary)").fetchall()}
    assert "ext_chzt" in pcols
    assert "ext_ph" in pcols
    assert "waga_kg" in pcols

    prow = conn.execute("SELECT punkt_nazwa, ph FROM chzt_pomiary WHERE id=1").fetchone()
    assert prow["punkt_nazwa"] == "hala"
    assert prow["ph"] == 10

    conn.execute(
        "INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at) "
        "VALUES ('2026-04-11T08:00:00', 8, '2026-04-11T08:00:00')"
    )
    conn.execute(
        "INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at) "
        "VALUES ('2026-04-11T14:00:00', 8, '2026-04-11T14:00:00')"
    )
    conn.commit()
    conn.close()


def test_migration_idempotent_on_fresh_db():
    """Running init_chzt_tables twice on a fresh DB is a no-op after first."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    init_chzt_tables(conn)
    init_chzt_tables(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(chzt_sesje)").fetchall()}
    assert "dt_start" in cols
    assert "data" not in cols
    conn.close()


def test_migration_mbr_users_rola_check_includes_produkcja():
    """mbr_users.rola CHECK must include 'produkcja' after init_mbr_tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    conn.execute(
        "INSERT INTO mbr_users (login, password_hash, rola, imie_nazwisko) "
        "VALUES ('mag1', 'hash', 'produkcja', 'Jan Magazyn')"
    )
    conn.commit()
    row = conn.execute("SELECT rola FROM mbr_users WHERE login='mag1'").fetchone()
    assert row["rola"] == "produkcja"
    conn.close()


# ───────────────────────────────────────────────────────────────
# Session helpers (redesign: on-demand, max 1 open)
# ───────────────────────────────────────────────────────────────

from mbr.chzt.models import get_active_session, create_session


def test_create_session_returns_id_and_seeds_pomiary(db):
    sid = create_session(db, created_by=1, n_kontenery=3)
    db.commit()
    assert isinstance(sid, int)

    row = db.execute(
        "SELECT dt_start, n_kontenery, finalized_at FROM chzt_sesje WHERE id=?", (sid,)
    ).fetchone()
    assert row["n_kontenery"] == 3
    assert row["finalized_at"] is None
    assert "T" in row["dt_start"]

    pomiary = db.execute(
        "SELECT punkt_nazwa FROM chzt_pomiary WHERE sesja_id=? ORDER BY kolejnosc", (sid,)
    ).fetchall()
    names = [r["punkt_nazwa"] for r in pomiary]
    assert names == ["hala", "rura", "kontener 1", "kontener 2", "kontener 3", "szambiarka"]


def test_create_session_raises_when_another_open(db):
    create_session(db, created_by=1, n_kontenery=3)
    db.commit()
    with pytest.raises(ValueError) as exc:
        create_session(db, created_by=1, n_kontenery=5)
    assert "already_open" in str(exc.value)


def test_create_session_ok_after_previous_finalized(db):
    sid1 = create_session(db, created_by=1, n_kontenery=3)
    db.execute("UPDATE chzt_sesje SET finalized_at=? WHERE id=?", ("2026-04-18T12:00:00", sid1))
    db.commit()
    sid2 = create_session(db, created_by=2, n_kontenery=8)
    db.commit()
    assert sid2 != sid1


def test_get_active_session_returns_open_one(db):
    sid = create_session(db, created_by=1, n_kontenery=3)
    db.commit()
    active = get_active_session(db)
    assert active is not None
    assert active["id"] == sid
    assert active["finalized_at"] is None


def test_get_active_session_returns_none_when_no_open(db):
    assert get_active_session(db) is None
    sid = create_session(db, created_by=1, n_kontenery=1)
    db.execute("UPDATE chzt_sesje SET finalized_at=? WHERE id=?", ("2026-04-18T12:00:00", sid))
    db.commit()
    assert get_active_session(db) is None


# ───────────────────────────────────────────────────────────────
# T3: ext fields in pomiar/session helpers + dt_start sort
# ───────────────────────────────────────────────────────────────


def test_update_pomiar_writes_ext_fields(db):
    sid = create_session(db, created_by=1, n_kontenery=0)
    db.commit()
    pid = db.execute(
        "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='szambiarka'", (sid,)
    ).fetchone()["id"]
    update_pomiar(db, pid, {
        "ph": 11, "p1": 25000, "p2": 26000, "p3": None, "p4": None, "p5": None,
        "ext_chzt": 13250, "ext_ph": 11, "waga_kg": 19060,
    }, updated_by=1)
    db.commit()
    row = db.execute(
        "SELECT ph, ext_chzt, ext_ph, waga_kg, srednia FROM chzt_pomiary WHERE id=?", (pid,)
    ).fetchone()
    assert row["ph"] == 11
    assert row["ext_chzt"] == 13250
    assert row["ext_ph"] == 11
    assert row["waga_kg"] == 19060
    assert row["srednia"] == 25500


def test_update_pomiar_partial_keeps_other_fields(db):
    """Partial-update semantics: keys not in new_values retain their existing value."""
    sid = create_session(db, created_by=1, n_kontenery=0)
    db.commit()
    pid = db.execute(
        "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='hala'", (sid,)
    ).fetchone()["id"]
    # First write ph + p1 + p2
    update_pomiar(db, pid, {"ph": 10, "p1": 1000, "p2": 2000}, updated_by=1)
    db.commit()
    # Second write only ext_chzt — ph/p1/p2 must be preserved
    update_pomiar(db, pid, {"ext_chzt": 5000}, updated_by=1)
    db.commit()
    row = db.execute(
        "SELECT ph, p1, p2, ext_chzt, srednia FROM chzt_pomiary WHERE id=?", (pid,)
    ).fetchone()
    assert row["ph"] == 10
    assert row["p1"] == 1000
    assert row["p2"] == 2000
    assert row["ext_chzt"] == 5000
    assert row["srednia"] == 1500


def test_get_pomiar_includes_ext_fields(db):
    sid = create_session(db, created_by=1, n_kontenery=0)
    db.commit()
    pid = db.execute(
        "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='szambiarka'", (sid,)
    ).fetchone()["id"]
    update_pomiar(db, pid, {"ext_chzt": 13250}, updated_by=1)
    db.commit()
    p = get_pomiar(db, pid)
    assert "ext_chzt" in p
    assert p["ext_chzt"] == 13250
    assert p["ext_ph"] is None
    assert p["waga_kg"] is None


def test_get_session_with_pomiary_includes_ext_fields(db):
    sid = create_session(db, created_by=1, n_kontenery=0)
    db.commit()
    s = get_session_with_pomiary(db, sid)
    for p in s["punkty"]:
        assert "ext_chzt" in p
        assert "ext_ph" in p
        assert "waga_kg" in p


def test_get_session_with_pomiary_uses_dt_start_not_data(db):
    sid = create_session(db, created_by=1, n_kontenery=0)
    db.commit()
    s = get_session_with_pomiary(db, sid)
    assert "dt_start" in s
    assert "data" not in s
    assert "T" in s["dt_start"]


def test_list_sessions_paginated_sorts_by_dt_start_desc(db):
    for dt in ["2026-04-10T08:00:00", "2026-04-12T10:00:00", "2026-04-11T14:00:00"]:
        db.execute(
            "INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at, created_by) "
            "VALUES (?, 0, ?, 1)", (dt, dt)
        )
    db.commit()
    page = list_sessions_paginated(db, page=1, per_page=10)
    dts = [s["dt_start"] for s in page["sesje"]]
    assert dts[0].startswith("2026-04-12")
    assert dts[1].startswith("2026-04-11")
    assert dts[2].startswith("2026-04-10")


def test_list_sessions_paginated_returns_dt_start_not_data(db):
    db.execute(
        "INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at, created_by) "
        "VALUES ('2026-04-18T08:00:00', 0, '2026-04-18T08:00:00', 1)"
    )
    db.commit()
    page = list_sessions_paginated(db, page=1, per_page=10)
    s = page["sesje"][0]
    assert "dt_start" in s
    assert s["dt_start"] == "2026-04-18T08:00:00"
    assert "data" not in s


# ───────────────────────────────────────────────────────────────
# T4: API endpoints /active, /new, /<int:id>
# ───────────────────────────────────────────────────────────────


def test_session_active_returns_null_when_no_open(client, db):
    resp = client.get("/api/chzt/session/active")
    assert resp.status_code == 200
    assert resp.get_json() == {"session": None}


def test_session_active_returns_open_session(client, db):
    r1 = client.post("/api/chzt/session/new", json={"n_kontenery": 8})
    assert r1.status_code == 200
    sid = r1.get_json()["session"]["id"]
    r2 = client.get("/api/chzt/session/active")
    assert r2.status_code == 200
    assert r2.get_json()["session"]["id"] == sid


def test_session_new_creates_and_returns_session(client, db):
    resp = client.post("/api/chzt/session/new", json={"n_kontenery": 3})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["session"]["n_kontenery"] == 3
    assert len(data["session"]["punkty"]) == 6  # hala + rura + 3 kontener + szambiarka


def test_session_new_default_n_kontenery(client, db):
    resp = client.post("/api/chzt/session/new", json={})
    assert resp.status_code == 200
    assert resp.get_json()["session"]["n_kontenery"] == 8


def test_session_new_rejects_out_of_range(client, db):
    r1 = client.post("/api/chzt/session/new", json={"n_kontenery": -1})
    assert r1.status_code == 400
    r2 = client.post("/api/chzt/session/new", json={"n_kontenery": 21})
    assert r2.status_code == 400


def test_session_new_409_when_already_open(client, db):
    client.post("/api/chzt/session/new", json={"n_kontenery": 3})
    resp = client.post("/api/chzt/session/new", json={"n_kontenery": 3})
    assert resp.status_code == 409


def test_session_new_after_finalize_ok(client, db):
    r1 = client.post("/api/chzt/session/new", json={"n_kontenery": 0})
    sid1 = r1.get_json()["session"]["id"]
    for p in r1.get_json()["session"]["punkty"]:
        client.put(f"/api/chzt/pomiar/{p['id']}", json={"ph": 10, "p1": 1, "p2": 2})
    client.post(f"/api/chzt/session/{sid1}/finalize")

    r2 = client.post("/api/chzt/session/new", json={"n_kontenery": 0})
    assert r2.status_code == 200
    assert r2.get_json()["session"]["id"] != sid1


def test_get_session_by_int_id(client, db):
    r1 = client.post("/api/chzt/session/new", json={"n_kontenery": 2})
    sid = r1.get_json()["session"]["id"]
    r2 = client.get(f"/api/chzt/session/{sid}")
    assert r2.status_code == 200
    assert r2.get_json()["session"]["id"] == sid


def test_get_session_by_int_id_404(client, db):
    resp = client.get("/api/chzt/session/99999")
    assert resp.status_code == 404


def test_session_new_logs_audit(client, db):
    client.post("/api/chzt/session/new", json={"n_kontenery": 3})
    rows = db.execute(
        "SELECT event_type FROM audit_log WHERE event_type='chzt.session.created'"
    ).fetchall()
    assert len(rows) == 1


# ───────────────────────────────────────────────────────────────
# T5: RBAC per-field in PUT /api/chzt/pomiar/<id>
# ───────────────────────────────────────────────────────────────


@pytest.fixture
def produkcja_client(monkeypatch, db):
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
        sess["user"] = {"login": "mag", "rola": "produkcja", "imie_nazwisko": "Jan Magazyn"}
    return c


def _bootstrap_session_with_lab(client):
    """Utility: create open session as lab (helper)."""
    r = client.post("/api/chzt/session/new", json={"n_kontenery": 0})
    return r.get_json()["session"]


def test_lab_put_pomiar_can_write_internal_fields(client, db):
    s = _bootstrap_session_with_lab(client)
    pid = s["punkty"][0]["id"]
    resp = client.put(f"/api/chzt/pomiar/{pid}", json={
        "ph": 10, "p1": 100, "p2": 200
    })
    assert resp.status_code == 200
    row = db.execute("SELECT ph, p1, p2, ext_chzt FROM chzt_pomiary WHERE id=?", (pid,)).fetchone()
    assert row["ph"] == 10
    assert row["p1"] == 100


def test_lab_put_pomiar_cannot_write_ext_fields(client, db):
    s = _bootstrap_session_with_lab(client)
    pid = s["punkty"][0]["id"]
    client.put(f"/api/chzt/pomiar/{pid}", json={
        "ph": 10, "p1": 100, "p2": 200,
        "ext_chzt": 99999, "ext_ph": 99, "waga_kg": 99999,
    })
    row = db.execute(
        "SELECT ph, ext_chzt, ext_ph, waga_kg FROM chzt_pomiary WHERE id=?", (pid,)
    ).fetchone()
    assert row["ph"] == 10
    assert row["ext_chzt"] is None
    assert row["ext_ph"] is None
    assert row["waga_kg"] is None


def test_produkcja_put_pomiar_can_write_ext_fields(produkcja_client, client, db):
    s = _bootstrap_session_with_lab(client)
    pid = s["punkty"][-1]["id"]  # szambiarka
    resp = produkcja_client.put(f"/api/chzt/pomiar/{pid}", json={
        "ext_chzt": 13250, "ext_ph": 11, "waga_kg": 19060
    })
    assert resp.status_code == 200
    row = db.execute(
        "SELECT ext_chzt, ext_ph, waga_kg, ph FROM chzt_pomiary WHERE id=?", (pid,)
    ).fetchone()
    assert row["ext_chzt"] == 13250
    assert row["ext_ph"] == 11
    assert row["waga_kg"] == 19060
    assert row["ph"] is None


def test_produkcja_put_pomiar_cannot_write_internal(produkcja_client, client, db):
    s = _bootstrap_session_with_lab(client)
    client.put(f"/api/chzt/pomiar/{s['punkty'][0]['id']}", json={"ph": 10, "p1": 100, "p2": 200})
    pid = s["punkty"][0]["id"]
    produkcja_client.put(f"/api/chzt/pomiar/{pid}", json={"ph": 99, "ext_chzt": 5000})
    row = db.execute("SELECT ph, ext_chzt FROM chzt_pomiary WHERE id=?", (pid,)).fetchone()
    assert row["ph"] == 10  # NOT overwritten by produkcja
    assert row["ext_chzt"] == 5000


def test_produkcja_cannot_create_session(produkcja_client, db):
    resp = produkcja_client.post("/api/chzt/session/new", json={"n_kontenery": 8})
    assert resp.status_code == 403


def test_produkcja_can_view_history(produkcja_client, client, db):
    _bootstrap_session_with_lab(client)
    resp = produkcja_client.get("/api/chzt/history")
    assert resp.status_code == 200


def test_admin_put_pomiar_can_write_all_fields(admin_client, client, db):
    s = _bootstrap_session_with_lab(client)
    pid = s["punkty"][-1]["id"]
    resp = admin_client.put(f"/api/chzt/pomiar/{pid}", json={
        "ph": 10, "p1": 100, "p2": 200,
        "ext_chzt": 5000, "ext_ph": 11, "waga_kg": 1000,
    })
    assert resp.status_code == 200
    row = db.execute(
        "SELECT ph, p1, ext_chzt, ext_ph, waga_kg FROM chzt_pomiary WHERE id=?", (pid,)
    ).fetchone()
    assert row["ph"] == 10
    assert row["p1"] == 100
    assert row["ext_chzt"] == 5000


# ───────────────────────────────────────────────────────────────
# T6: Day endpoint — DATE(dt_start) lookup + ext fields in response
# ───────────────────────────────────────────────────────────────


def test_day_endpoint_finds_by_dt_start_date_and_returns_ext_fields(client, db):
    """Session spanning midnight (starts 22:00 day X, finalizes 06:00 day X+1)
    is found by /day/X but NOT /day/X+1. Response includes ext_chzt/ext_ph/waga_kg."""
    # Insert directly — can't use POST /new because we need to control dt_start
    db.execute(
        "INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at, finalized_at, finalized_by) "
        "VALUES ('2026-04-18T22:00:00', 0, '2026-04-18T22:00:00', '2026-04-19T06:00:00', 1)"
    )
    sid = db.execute(
        "SELECT id FROM chzt_sesje WHERE dt_start='2026-04-18T22:00:00'"
    ).fetchone()["id"]
    # Seed pomiary including szambiarka with ext fields
    for idx, name in enumerate(["hala", "rura", "szambiarka"], start=1):
        is_szamb = name == "szambiarka"
        db.execute(
            "INSERT INTO chzt_pomiary (sesja_id, punkt_nazwa, kolejnosc, ph, p1, p2, srednia, "
            "ext_chzt, ext_ph, waga_kg, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sid, name, idx, 10, 15000, 16000, 15500,
                13250 if is_szamb else None,
                11 if is_szamb else None,
                19060 if is_szamb else None,
                "2026-04-18T23:00:00",
            ),
        )
    db.commit()

    # /day/2026-04-18 — finds the session (matches DATE(dt_start))
    r1 = client.get("/api/chzt/day/2026-04-18")
    assert r1.status_code == 200
    body = r1.get_json()
    assert "dt_start" in body
    assert body["dt_start"].startswith("2026-04-18T22")
    assert "data" not in body  # old response key removed
    szamb = next(p for p in body["punkty"] if p["nazwa"] == "szambiarka")
    assert szamb["ext_chzt"] == 13250
    assert szamb["ext_ph"] == 11
    assert szamb["waga_kg"] == 19060

    # /day/2026-04-19 — 404 (session started the 18th, not the 19th)
    r2 = client.get("/api/chzt/day/2026-04-19")
    assert r2.status_code == 404


# ───────────────────────────────────────────────────────────────
# T10: E2E scenarios
# ───────────────────────────────────────────────────────────────


def test_crossing_midnight_session_lifecycle(client, db):
    """Night shift: session starts 22:15 day X, finalizes 06:05 day X+1."""
    r1 = client.post("/api/chzt/session/new", json={"n_kontenery": 2})
    assert r1.status_code == 200
    sid = r1.get_json()["session"]["id"]

    # Simulate evening start
    db.execute(
        "UPDATE chzt_sesje SET dt_start=? WHERE id=?",
        ("2026-04-18T22:15:00", sid),
    )
    db.commit()

    # Fill all points
    r_refresh = client.get(f"/api/chzt/session/{sid}").get_json()["session"]
    for p in r_refresh["punkty"]:
        client.put(f"/api/chzt/pomiar/{p['id']}", json={
            "ph": 10, "p1": 15000, "p2": 16000
        })

    # Finalize + simulate morning completion
    r_fin = client.post(f"/api/chzt/session/{sid}/finalize")
    assert r_fin.status_code == 200
    db.execute(
        "UPDATE chzt_sesje SET finalized_at=? WHERE id=?",
        ("2026-04-19T06:05:00", sid),
    )
    db.commit()

    # History shows the session with correct boundary
    r_hist = client.get("/api/chzt/history").get_json()
    assert r_hist["sesje"][0]["id"] == sid
    assert r_hist["sesje"][0]["dt_start"].startswith("2026-04-18T22")
    assert r_hist["sesje"][0]["finalized_at"].startswith("2026-04-19T06")

    # /day/2026-04-18 finds it (DATE(dt_start) matches)
    r_day = client.get("/api/chzt/day/2026-04-18")
    assert r_day.status_code == 200
    assert r_day.get_json()["dt_start"].startswith("2026-04-18T22")

    # /day/2026-04-19 does NOT find it (session started on 18th)
    r_day_next = client.get("/api/chzt/day/2026-04-19")
    assert r_day_next.status_code == 404

    # No active session remaining
    r_active = client.get("/api/chzt/session/active").get_json()
    assert r_active["session"] is None

    # New session can be created after finalize
    r_new = client.post("/api/chzt/session/new", json={"n_kontenery": 3})
    assert r_new.status_code == 200
    assert r_new.get_json()["session"]["id"] != sid


def test_produkcja_fills_ext_after_lab_finalizes(produkcja_client, client, db):
    """Lab fills pomiary + finalizes. Produkcja then fills ext fields on szambiarka."""
    # Lab creates + fills all points
    r = client.post("/api/chzt/session/new", json={"n_kontenery": 0})
    sid = r.get_json()["session"]["id"]
    for p in r.get_json()["session"]["punkty"]:
        client.put(f"/api/chzt/pomiar/{p['id']}", json={"ph": 10, "p1": 100, "p2": 200})
    client.post(f"/api/chzt/session/{sid}/finalize")

    # Locate szambiarka pomiar id
    szamb_pid = db.execute(
        "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='szambiarka'", (sid,)
    ).fetchone()["id"]

    # Produkcja writes ext fields on finalized session
    resp = produkcja_client.put(f"/api/chzt/pomiar/{szamb_pid}", json={
        "ext_chzt": 13250, "ext_ph": 11, "waga_kg": 19060
    })
    assert resp.status_code == 200

    row = db.execute(
        "SELECT ext_chzt, ext_ph, waga_kg, ph FROM chzt_pomiary WHERE id=?", (szamb_pid,)
    ).fetchone()
    assert row["ext_chzt"] == 13250
    assert row["ext_ph"] == 11
    assert row["waga_kg"] == 19060
    assert row["ph"] == 10  # lab's value, untouched by produkcja

    # Audit logs both updates (lab + produkcja)
    pomiar_events = db.execute(
        "SELECT event_type FROM audit_log WHERE event_type='chzt.pomiar.updated' AND entity_id=?",
        (szamb_pid,),
    ).fetchall()
    assert len(pomiar_events) >= 2


def test_produkcja_blur_ext_input_triggers_ext_save_via_js_path(produkcja_client, client, db):
    """Regression: getRowValues must include ext_* fields when produkcja blurs
    an ext input. Simulates the exact payload the JS saveRow() builds, verifying
    the full stack (JS payload shape → server RBAC filter → DB) writes ext data."""
    s = _bootstrap_session_with_lab(client)
    szamb_pid = s["punkty"][-1]["id"]

    # Simulate what the JS would send after fix: payload containing ONLY the keys
    # that exist as non-disabled DOM inputs in the ext section for produkcja role
    # (i.e. ext_ph, ext_chzt, waga_kg). No ph/p1-p5 keys at all (those inputs are
    # disabled for produkcja in the main table).
    resp = produkcja_client.put(f"/api/chzt/pomiar/{szamb_pid}", json={
        "ext_ph": 11, "ext_chzt": 13250, "waga_kg": 19060,
    })
    assert resp.status_code == 200

    row = db.execute(
        "SELECT ext_chzt, ext_ph, waga_kg FROM chzt_pomiary WHERE id=?", (szamb_pid,)
    ).fetchone()
    assert row["ext_ph"] == 11
    assert row["ext_chzt"] == 13250
    assert row["waga_kg"] == 19060


def test_patch_session_rejects_bool_n_kontenery(client, db):
    """Regression: api_session_patch must exclude bool from int acceptance (like api_session_create)."""
    r1 = client.post("/api/chzt/session/new", json={"n_kontenery": 3})
    sid = r1.get_json()["session"]["id"]
    resp = client.patch(f"/api/chzt/session/{sid}", json={"n_kontenery": True})
    assert resp.status_code == 400
