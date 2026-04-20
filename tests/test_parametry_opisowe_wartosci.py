"""PR1: opisowe_wartosci column + CRUD + validation."""

import json as _json
import sqlite3
from contextlib import contextmanager

import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


@pytest.fixture
def client(monkeypatch, db):
    """Flask test client with db_session monkeypatched to shared in-memory db."""
    import mbr.db
    import mbr.parametry.routes
    from mbr.app import app

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.parametry.routes, "db_session", fake_db_session)
    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["user"] = {"username": "admin_test", "rola": "admin", "id": 1}
        yield c


def test_opisowe_wartosci_column_exists(db):
    """Schema migration adds opisowe_wartosci column to parametry_analityczne."""
    cols = [r[1] for r in db.execute("PRAGMA table_info(parametry_analityczne)")]
    assert "opisowe_wartosci" in cols


def _mk_param(db, kod="zapach", typ="jakosciowy"):
    cur = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision) "
        "VALUES (?, ?, ?, 'lab', 0)",
        (kod, kod.capitalize(), typ),
    )
    db.commit()
    return cur.lastrowid


def test_put_accepts_opisowe_wartosci_for_jakosciowy(client, db):
    pid = _mk_param(db, kod="zapach", typ="jakosciowy")
    payload = {"opisowe_wartosci": ["charakterystyczny", "obcy", "brak"]}
    r = client.put(f"/api/parametry/{pid}", json=payload)
    assert r.status_code == 200
    row = db.execute(
        "SELECT opisowe_wartosci FROM parametry_analityczne WHERE id=?", (pid,)
    ).fetchone()
    assert _json.loads(row["opisowe_wartosci"]) == ["charakterystyczny", "obcy", "brak"]


def test_put_rejects_empty_list_for_jakosciowy(client, db):
    pid = _mk_param(db, kod="barwa", typ="jakosciowy")
    r = client.put(f"/api/parametry/{pid}", json={"opisowe_wartosci": []})
    assert r.status_code == 400
    assert "opisowe_wartosci" in r.get_json()["error"].lower()


def test_put_rejects_non_list_for_jakosciowy(client, db):
    pid = _mk_param(db, kod="wyglad", typ="jakosciowy")
    r = client.put(f"/api/parametry/{pid}", json={"opisowe_wartosci": "foo"})
    assert r.status_code == 400


def test_put_rejects_non_string_items(client, db):
    pid = _mk_param(db, kod="smak", typ="jakosciowy")
    r = client.put(f"/api/parametry/{pid}", json={"opisowe_wartosci": ["ok", 5]})
    assert r.status_code == 400


def test_put_ignores_opisowe_wartosci_for_non_jakosciowy(client, db):
    pid = _mk_param(db, kod="gestosc", typ="bezposredni")
    r = client.put(f"/api/parametry/{pid}", json={"opisowe_wartosci": ["a", "b"]})
    assert r.status_code == 200
    row = db.execute(
        "SELECT opisowe_wartosci FROM parametry_analityczne WHERE id=?", (pid,)
    ).fetchone()
    assert row["opisowe_wartosci"] is None


def test_put_changing_typ_to_jakosciowy_requires_opisowe_wartosci(client, db):
    pid = _mk_param(db, kod="test1", typ="bezposredni")
    r = client.put(f"/api/parametry/{pid}", json={"typ": "jakosciowy"})
    assert r.status_code == 400


def test_put_changing_typ_to_jakosciowy_with_values_succeeds(client, db):
    """Happy path: admin changes typ → jakosciowy AND provides opisowe_wartosci → 200."""
    pid = _mk_param(db, kod="happyt", typ="bezposredni")
    # No ebr_wyniki → guard passes.
    r = client.put(
        f"/api/parametry/{pid}",
        json={"typ": "jakosciowy", "opisowe_wartosci": ["a", "b"]},
    )
    assert r.status_code == 200
    row = db.execute(
        "SELECT typ, opisowe_wartosci FROM parametry_analityczne WHERE id=?", (pid,)
    ).fetchone()
    assert row["typ"] == "jakosciowy"
    assert _json.loads(row["opisowe_wartosci"]) == ["a", "b"]


def test_put_typ_guard_rejects_change_with_historical_results(client, db):
    """Cannot change typ once ebr_wyniki exist for this param."""
    pid = _mk_param(db, kod="histtest", typ="bezposredni")
    db.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, tag, kod_parametru, wartosc, w_limicie, dt_wpisu, wpisal) "
        "VALUES (1, 'lab', 'histtest', 'histtest', 1.5, 1, '2024-01-01', 'test')",
    )
    db.commit()
    r = client.put(
        f"/api/parametry/{pid}",
        json={"typ": "jakosciowy", "opisowe_wartosci": ["a", "b"]},
    )
    assert r.status_code == 409


def test_post_creates_jakosciowy_param_with_wartosci(client, db):
    payload = {
        "kod": "zapach",
        "label": "Zapach",
        "typ": "jakosciowy",
        "grupa": "lab",
        "opisowe_wartosci": ["charakterystyczny", "obcy", "brak"],
    }
    r = client.post("/api/parametry", json=payload)
    assert r.status_code == 200, r.get_json()
    new_id = r.get_json()["id"]
    row = db.execute(
        "SELECT typ, opisowe_wartosci FROM parametry_analityczne WHERE id=?", (new_id,)
    ).fetchone()
    assert row["typ"] == "jakosciowy"
    assert _json.loads(row["opisowe_wartosci"]) == ["charakterystyczny", "obcy", "brak"]


def test_post_rejects_jakosciowy_without_wartosci(client, db):
    payload = {"kod": "barwa", "label": "Barwa", "typ": "jakosciowy", "grupa": "lab"}
    r = client.post("/api/parametry", json=payload)
    assert r.status_code == 400


def test_post_ignores_opisowe_wartosci_for_non_jakosciowy(client, db):
    payload = {
        "kod": "gestosc",
        "label": "Gęstość",
        "typ": "bezposredni",
        "grupa": "lab",
        "opisowe_wartosci": ["a", "b"],
    }
    r = client.post("/api/parametry", json=payload)
    assert r.status_code == 200
    new_id = r.get_json()["id"]
    row = db.execute(
        "SELECT opisowe_wartosci FROM parametry_analityczne WHERE id=?", (new_id,)
    ).fetchone()
    assert row["opisowe_wartosci"] is None


def test_list_exposes_opisowe_wartosci(client, db):
    """GET /api/parametry/list returns opisowe_wartosci as JSON string."""
    pid = _mk_param(db, kod="zapach_list", typ="jakosciowy")
    db.execute(
        "UPDATE parametry_analityczne SET opisowe_wartosci=? WHERE id=?",
        (_json.dumps(["a", "b"]), pid),
    )
    db.commit()
    r = client.get("/api/parametry/list")
    assert r.status_code == 200
    rows = r.get_json()
    row = next((x for x in rows if x["id"] == pid), None)
    assert row is not None
    assert "opisowe_wartosci" in row
    assert _json.loads(row["opisowe_wartosci"]) == ["a", "b"]


def test_existing_params_unaffected_by_new_column(client, db):
    """A bezposredni param without opisowe_wartosci continues to work: PUT updates label, no errors."""
    pid = _mk_param(db, kod="gestosc2", typ="bezposredni")
    r = client.put(f"/api/parametry/{pid}", json={"label": "Gęstość v2"})
    assert r.status_code == 200
    row = db.execute(
        "SELECT label, opisowe_wartosci FROM parametry_analityczne WHERE id=?", (pid,)
    ).fetchone()
    assert row["label"] == "Gęstość v2"
    assert row["opisowe_wartosci"] is None
