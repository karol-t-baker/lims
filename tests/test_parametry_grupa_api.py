"""Tests for grupa field on /api/parametry endpoints."""

import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _make_client(monkeypatch, db, rola="admin"):
    import mbr.db
    import mbr.parametry.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.parametry.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": rola, "worker_id": None}
    return c


@pytest.fixture
def client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="admin")


def test_post_parametry_with_grupa_zewn_persists(client, db):
    r = client.post("/api/parametry", json={
        "kod": "tpc", "label": "Total plate count", "typ": "bezposredni", "grupa": "zewn",
    })
    assert r.status_code == 200, r.get_json()
    row = db.execute("SELECT grupa FROM parametry_analityczne WHERE kod='tpc'").fetchone()
    assert row["grupa"] == "zewn"


def test_post_parametry_without_grupa_defaults_lab(client, db):
    r = client.post("/api/parametry", json={"kod": "x", "label": "X", "typ": "bezposredni"})
    assert r.status_code == 200
    row = db.execute("SELECT grupa FROM parametry_analityczne WHERE kod='x'").fetchone()
    assert row["grupa"] == "lab"


def test_post_parametry_rejects_unknown_grupa(client, db):
    r = client.post("/api/parametry", json={
        "kod": "x", "label": "X", "typ": "bezposredni", "grupa": "mikrobio",
    })
    assert r.status_code == 400
    assert "grupa" in (r.get_json().get("error") or "").lower()
    # Must not have created the row
    assert db.execute("SELECT COUNT(*) FROM parametry_analityczne WHERE kod='x'").fetchone()[0] == 0


@pytest.fixture
def client_non_admin(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="lab")


def _seed_param(db, kod="sm", grupa="lab"):
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa) VALUES (?, ?, 'bezposredni', ?)",
        (kod, kod.upper(), grupa),
    )
    db.commit()
    return db.execute("SELECT id FROM parametry_analityczne WHERE kod=?", (kod,)).fetchone()["id"]


def test_put_parametry_admin_can_change_grupa(client, db):
    pid = _seed_param(db, "tpc", "lab")
    r = client.put(f"/api/parametry/{pid}", json={"grupa": "zewn"})
    assert r.status_code == 200
    row = db.execute("SELECT grupa FROM parametry_analityczne WHERE id=?", (pid,)).fetchone()
    assert row["grupa"] == "zewn"


def test_put_parametry_rejects_unknown_grupa(client, db):
    pid = _seed_param(db, "tpc", "lab")
    r = client.put(f"/api/parametry/{pid}", json={"grupa": "nonsense"})
    assert r.status_code == 400
    # DB unchanged
    row = db.execute("SELECT grupa FROM parametry_analityczne WHERE id=?", (pid,)).fetchone()
    assert row["grupa"] == "lab"


def test_put_parametry_non_admin_cannot_change_grupa(client_non_admin, db):
    """Grupa is admin-only, like typ/aktywny. Non-admin PUT with grupa: ignored (silently dropped from allowed set).
    The response may succeed (200) or reject (400 'No valid fields') depending on whether other fields are also sent.
    Key invariant: DB row's grupa must NOT change."""
    pid = _seed_param(db, "tpc", "lab")
    r = client_non_admin.put(f"/api/parametry/{pid}", json={"grupa": "zewn", "label": "new label"})
    # label IS allowed for non-admin, so request returns 200, grupa silently dropped
    assert r.status_code == 200
    row = db.execute("SELECT grupa, label FROM parametry_analityczne WHERE id=?", (pid,)).fetchone()
    assert row["grupa"] == "lab"
    assert row["label"] == "new label"


def test_put_parametry_grupa_only_non_admin_rejected(client_non_admin, db):
    pid = _seed_param(db, "tpc", "lab")
    r = client_non_admin.put(f"/api/parametry/{pid}", json={"grupa": "zewn"})
    # No valid fields for non-admin to update
    assert r.status_code == 400
    row = db.execute("SELECT grupa FROM parametry_analityczne WHERE id=?", (pid,)).fetchone()
    assert row["grupa"] == "lab"


def test_binding_legacy_inherits_grupa_from_parametr(client, db):
    """Binding created via POST /api/parametry/etapy on a NON-pipeline product
    (legacy path → parametry_etapy) inherits grupa from parametry_analityczne."""
    pid = _seed_param(db, "tpc", "zewn")
    r = client.post("/api/parametry/etapy", json={
        "parametr_id": pid, "kontekst": "analiza_koncowa",
        "produkt": "TEST_LEGACY",  # no pipeline row in the fixture → legacy branch
        "min_limit": 0, "max_limit": 100,
    })
    assert r.status_code == 200, r.get_json()
    row = db.execute(
        "SELECT grupa FROM parametry_etapy WHERE parametr_id=? AND produkt='TEST_LEGACY'",
        (pid,),
    ).fetchone()
    assert row is not None
    assert row["grupa"] == "zewn"


def test_binding_legacy_honors_explicit_grupa_override(client, db):
    """Explicit 'grupa' in request body overrides the global default."""
    pid = _seed_param(db, "tpc", "zewn")  # global grupa='zewn'
    r = client.post("/api/parametry/etapy", json={
        "parametr_id": pid, "kontekst": "analiza_koncowa", "produkt": "TEST_LEGACY",
        "grupa": "lab",  # admin wants this particular binding to be 'lab' anyway
        "min_limit": 0, "max_limit": 100,
    })
    assert r.status_code == 200
    row = db.execute(
        "SELECT grupa FROM parametry_etapy WHERE parametr_id=? AND produkt='TEST_LEGACY'",
        (pid,),
    ).fetchone()
    assert row["grupa"] == "lab"


def test_binding_legacy_rejects_invalid_grupa(client, db):
    pid = _seed_param(db, "tpc", "lab")
    r = client.post("/api/parametry/etapy", json={
        "parametr_id": pid, "kontekst": "analiza_koncowa", "produkt": "TEST_LEGACY",
        "grupa": "mikrobio",
    })
    assert r.status_code == 400
    assert "grupa" in (r.get_json().get("error") or "").lower()
