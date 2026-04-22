"""Regression for PUT /api/pipeline/lab/ebr/<id>/korekta guard.

Before the fix, the endpoint filtered sesja rows by
`status IN ('nierozpoczety', 'w_trakcie')`, which blocked edits once the
session was closed even if the batch itself was still open. The loosened
guard delegates the decision to `edit_policy.is_sesja_editable` so a
laborant can correct a value after closing the session while the batch
is still in progress.
"""

import sqlite3

import pytest

from mbr.models import init_mbr_tables


class _NoCloseDB:
    """Delegate everything to the real connection but ignore close() so the
    in-memory DB survives across requests in the same test."""

    def __init__(self, conn):
        self._conn = conn

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _seed(db):
    db.execute(
        "INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, etapy_json, dt_utworzenia) "
        "VALUES (1, 'Chegina_K7', 1, 'active', '[]', '2026-04-22T00:00:00')"
    )
    db.execute(
        "INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, status, dt_start) "
        "VALUES (100, 1, 'K7-T-0001', 'K7/T', 'open', '2026-04-22T09:00:00')"
    )
    db.execute(
        "INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
        "VALUES (10, 'sulfonowanie', 'Sulfonowanie', 'cykliczny')"
    )
    db.execute(
        "INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
        "VALUES (11, 'analiza_koncowa', 'Analiza końcowa', 'jednorazowy')"
    )
    db.execute(
        "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) "
        "VALUES ('Chegina_K7', 10, 1)"
    )
    db.execute(
        "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) "
        "VALUES ('Chegina_K7', 11, 2)"
    )
    db.execute(
        "INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, dt_start) "
        "VALUES (1000, 100, 10, 1, 'zamkniety', '2026-04-22T10:00:00')"
    )
    db.execute(
        "INSERT INTO etap_korekty_katalog (id, etap_id, substancja, jednostka) "
        "VALUES (5, 10, 'Kwas cytrynowy', 'kg')"
    )
    db.commit()


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    _seed(conn)
    yield conn
    conn.close()


@pytest.fixture
def client(monkeypatch, db):
    import mbr.pipeline.lab_routes as lab_routes

    wrapped = _NoCloseDB(db)
    monkeypatch.setattr(lab_routes, "get_db", lambda: wrapped)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    c = app.test_client()
    with c.session_transaction() as s:
        s["user"] = {"login": "lab1", "rola": "laborant", "imie_nazwisko": None}
    yield c


def test_put_korekta_accepts_closed_sesja_when_batch_open(client, db):
    """PUT /korekta must succeed against a zamkniety sesja while the batch is open."""
    resp = client.put(
        "/api/pipeline/lab/ebr/100/korekta",
        json={"etap_id": 10, "substancja": "Kwas cytrynowy", "ilosc": 12.5},
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["ok"] is True
    assert body["sesja_id"] == 1000
    assert body["ilosc"] == 12.5


def test_put_korekta_rejects_when_batch_closed_and_not_last_stage(client, db):
    """Batch closed + sesja not in the last stage → 403 (edit_policy blocks)."""
    db.execute("UPDATE ebr_batches SET status='completed' WHERE ebr_id=100")
    db.commit()

    resp = client.put(
        "/api/pipeline/lab/ebr/100/korekta",
        json={"etap_id": 10, "substancja": "Kwas cytrynowy", "ilosc": 7.0},
    )
    assert resp.status_code == 403, resp.get_json()


def test_put_korekta_returns_400_when_no_sesja_exists(client, db):
    """No sesja for etap at all → 400, separate from the locked-sesja case."""
    db.execute("DELETE FROM ebr_etap_sesja WHERE ebr_id=100 AND etap_id=10")
    db.commit()

    resp = client.put(
        "/api/pipeline/lab/ebr/100/korekta",
        json={"etap_id": 10, "substancja": "Kwas cytrynowy", "ilosc": 1.0},
    )
    assert resp.status_code == 400
    assert "no session" in resp.get_json()["error"]


def test_post_pomiary_rejected_closed_batch_earlier_stage(client, db):
    db.execute("UPDATE ebr_batches SET status='completed' WHERE ebr_id=100")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (777, 'pX', 'X', 'bezposredni')")
    db.commit()
    resp = client.post("/api/pipeline/lab/ebr/100/etap/10/pomiary",
                       json={"sesja_id": 1000, "pomiary": [{"parametr_id": 777, "wartosc": 5}]})
    assert resp.status_code == 403, resp.get_json()


def test_post_pomiary_accepted_open_batch_on_closed_sesja(client, db):
    """Open batch + closed sesja → 200 (edit policy permits)."""
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (778, 'pY', 'Y', 'bezposredni')")
    db.commit()
    resp = client.post("/api/pipeline/lab/ebr/100/etap/10/pomiary",
                       json={"sesja_id": 1000, "pomiary": [{"parametr_id": 778, "wartosc": 3}]})
    assert resp.status_code == 200, resp.get_json()


def test_post_korekta_rejected_closed_batch_earlier_stage(client, db):
    db.execute("UPDATE ebr_batches SET status='completed' WHERE ebr_id=100")
    db.commit()
    resp = client.post("/api/pipeline/lab/ebr/100/korekta",
                       json={"sesja_id": 1000, "korekta_typ_id": 5, "ilosc": 10})
    assert resp.status_code == 403


def test_downstream_summary_endpoint(client, db):
    # Seed a sesja on analiza_koncowa (etap 11) + a pomiar so it counts as downstream activity.
    db.execute(
        "INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, dt_start) "
        "VALUES (1001, 100, 11, 1, 'zamkniety', '2026-04-22T13:00:00')"
    )
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ) "
        "VALUES (779, 'pZ', 'Z', 'bezposredni')"
    )
    db.execute(
        "INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, wpisal, dt_wpisu) "
        "VALUES (1001, 779, 9.0, 'lab1', '2026-04-22T13:00:00')"
    )
    db.commit()

    resp = client.get("/api/pipeline/lab/ebr/100/etap/10/downstream-summary")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["has_downstream"] is True
    assert any(s["etap_id"] == 11 and s["pomiary"] >= 1 for s in data["stages"])


def test_put_korekta_on_closed_sesja_emits_reedit_audit(client, db):
    """Writes that land on a zamkniety sesja must audit-log reedit=1."""
    resp = client.put("/api/pipeline/lab/ebr/100/korekta",
                      json={"etap_id": 10, "substancja": "Kwas cytrynowy", "ilosc": 7.5})
    assert resp.status_code == 200, resp.get_json()
    row = db.execute(
        "SELECT payload_json FROM audit_log "
        "WHERE event_type = 'ebr.wynik.updated' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None, "no audit row emitted"
    import json as _j
    payload = _j.loads(row["payload_json"])
    assert payload.get("reedit") == 1
