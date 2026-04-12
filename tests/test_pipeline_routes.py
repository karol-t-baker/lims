"""
tests/test_pipeline_routes.py — Integration tests for pipeline admin API routes.

Pattern: create in-memory SQLite with init_mbr_tables(), monkeypatch get_db in
mbr.pipeline.routes so every route uses the test DB, build Flask test client
with an admin session.
"""

import sqlite3
import pytest

from mbr.models import init_mbr_tables


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


class _NoCloseDB:
    """Proxy that delegates everything to the real connection but ignores close()."""

    def __init__(self, conn):
        self._conn = conn

    def close(self):
        pass  # keep in-memory DB alive across requests

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _make_client(monkeypatch, db, rola="admin"):
    """Build Flask test client with the in-memory db patched into pipeline routes."""
    import mbr.pipeline.routes as pipeline_routes

    wrapped = _NoCloseDB(db)
    monkeypatch.setattr(pipeline_routes, "get_db", lambda: wrapped)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    client = app.test_client()
    if rola is not None:
        with client.session_transaction() as sess:
            sess["user"] = {"login": "tester", "rola": rola, "imie_nazwisko": None}
    return client


@pytest.fixture
def admin_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="admin")


@pytest.fixture
def laborant_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="laborant")


# ---------------------------------------------------------------------------
# Helper: seed a parameter into in-memory db
# ---------------------------------------------------------------------------

def _seed_param(db, pid=9001, kod="ph", label="pH", typ="bezposredni"):
    db.execute(
        "INSERT OR IGNORE INTO parametry_analityczne (id, kod, label, typ) VALUES (?,?,?,?)",
        (pid, kod, label, typ),
    )
    db.commit()
    return pid


# ---------------------------------------------------------------------------
# test_create_etap
# ---------------------------------------------------------------------------

def test_create_etap(admin_client):
    resp = admin_client.post(
        "/api/pipeline/etapy",
        json={"kod": "amid", "nazwa": "Amidowanie"},
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["kod"] == "amid"
    assert data["nazwa"] == "Amidowanie"
    assert data["aktywny"] == 1
    assert data["typ_cyklu"] == "jednorazowy"


def test_create_etap_with_optional_fields(admin_client):
    resp = admin_client.post(
        "/api/pipeline/etapy",
        json={"kod": "czwart", "nazwa": "Czwartorzędowanie", "typ_cyklu": "cykliczny", "opis": "Test opis"},
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["typ_cyklu"] == "cykliczny"
    assert data["opis"] == "Test opis"


# ---------------------------------------------------------------------------
# test_create_etap_requires_admin
# ---------------------------------------------------------------------------

def test_create_etap_requires_admin(laborant_client):
    resp = laborant_client.post(
        "/api/pipeline/etapy",
        json={"kod": "amid", "nazwa": "Amidowanie"},
    )
    assert resp.status_code == 403


def test_create_etap_requires_login(monkeypatch, db):
    client = _make_client(monkeypatch, db, rola=None)
    resp = client.post(
        "/api/pipeline/etapy",
        json={"kod": "amid", "nazwa": "Amidowanie"},
    )
    # Unauthenticated → redirect to login
    assert resp.status_code in (302, 403)


# ---------------------------------------------------------------------------
# test_list_etapy
# ---------------------------------------------------------------------------

def test_list_etapy(admin_client):
    admin_client.post("/api/pipeline/etapy", json={"kod": "amid", "nazwa": "Amidowanie"})
    admin_client.post("/api/pipeline/etapy", json={"kod": "czwart", "nazwa": "Czwartorzędowanie"})

    resp = admin_client.get("/api/pipeline/etapy")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert len(data) == 2
    kody = [r["kod"] for r in data]
    assert "amid" in kody
    assert "czwart" in kody


def test_list_etapy_empty(admin_client):
    resp = admin_client.get("/api/pipeline/etapy")
    assert resp.status_code == 200
    assert resp.get_json() == []


# ---------------------------------------------------------------------------
# test_get_etap_detail
# ---------------------------------------------------------------------------

def test_get_etap_detail(admin_client, db):
    _seed_param(db, 9001, "ph", "pH")

    # Create etap
    cr = admin_client.post("/api/pipeline/etapy", json={"kod": "amid", "nazwa": "Amidowanie"})
    etap_id = cr.get_json()["id"]

    # Add param
    admin_client.post(
        f"/api/pipeline/etapy/{etap_id}/parametry",
        json={"parametr_id": 9001, "kolejnosc": 1},
    )

    resp = admin_client.get(f"/api/pipeline/etapy/{etap_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "etap" in data
    assert "parametry" in data
    assert "warunki" in data
    assert "korekty" in data
    assert data["etap"]["kod"] == "amid"
    assert len(data["parametry"]) == 1
    assert data["parametry"][0]["kod"] == "ph"


def test_get_etap_detail_not_found(admin_client):
    resp = admin_client.get("/api/pipeline/etapy/9999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# test_update_etap
# ---------------------------------------------------------------------------

def test_update_etap(admin_client):
    cr = admin_client.post("/api/pipeline/etapy", json={"kod": "amid", "nazwa": "Amidowanie"})
    etap_id = cr.get_json()["id"]

    resp = admin_client.put(
        f"/api/pipeline/etapy/{etap_id}",
        json={"nazwa": "Amidowanie v2", "typ_cyklu": "cykliczny"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["nazwa"] == "Amidowanie v2"
    assert data["typ_cyklu"] == "cykliczny"


def test_deactivate_etap(admin_client):
    cr = admin_client.post("/api/pipeline/etapy", json={"kod": "amid", "nazwa": "Amidowanie"})
    etap_id = cr.get_json()["id"]

    resp = admin_client.post(f"/api/pipeline/etapy/{etap_id}/deactivate")
    assert resp.status_code == 200

    detail = admin_client.get(f"/api/pipeline/etapy/{etap_id}").get_json()
    assert detail["etap"]["aktywny"] == 0


# ---------------------------------------------------------------------------
# test_add_parametr_to_etap
# ---------------------------------------------------------------------------

def test_add_parametr_to_etap(admin_client, db):
    _seed_param(db, 9001, "ph", "pH")
    _seed_param(db, 9002, "sm", "SM")

    cr = admin_client.post("/api/pipeline/etapy", json={"kod": "amid", "nazwa": "Amidowanie"})
    etap_id = cr.get_json()["id"]

    resp = admin_client.post(
        f"/api/pipeline/etapy/{etap_id}/parametry",
        json={"parametr_id": 9001, "kolejnosc": 1, "min_limit": 5.0, "max_limit": 9.0},
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["kod"] == "ph"
    assert data["min_limit"] == 5.0
    assert data["max_limit"] == 9.0


def test_update_parametr_in_etap(admin_client, db):
    _seed_param(db, 9001, "ph", "pH")
    cr = admin_client.post("/api/pipeline/etapy", json={"kod": "amid", "nazwa": "Amidowanie"})
    etap_id = cr.get_json()["id"]
    ep = admin_client.post(
        f"/api/pipeline/etapy/{etap_id}/parametry",
        json={"parametr_id": 9001, "kolejnosc": 1},
    ).get_json()
    ep_id = ep["id"]

    resp = admin_client.put(
        f"/api/pipeline/etapy/{etap_id}/parametry/{ep_id}",
        json={"min_limit": 6.0, "max_limit": 8.0},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["min_limit"] == 6.0
    assert data["max_limit"] == 8.0


def test_remove_parametr_from_etap(admin_client, db):
    _seed_param(db, 9001, "ph", "pH")
    cr = admin_client.post("/api/pipeline/etapy", json={"kod": "amid", "nazwa": "Amidowanie"})
    etap_id = cr.get_json()["id"]
    ep = admin_client.post(
        f"/api/pipeline/etapy/{etap_id}/parametry",
        json={"parametr_id": 9001, "kolejnosc": 1},
    ).get_json()
    ep_id = ep["id"]

    resp = admin_client.delete(f"/api/pipeline/etapy/{etap_id}/parametry/{ep_id}")
    assert resp.status_code == 200

    detail = admin_client.get(f"/api/pipeline/etapy/{etap_id}").get_json()
    assert detail["parametry"] == []


# ---------------------------------------------------------------------------
# test_add_warunek
# ---------------------------------------------------------------------------

def test_add_warunek(admin_client, db):
    _seed_param(db, 9001, "ph", "pH")
    cr = admin_client.post("/api/pipeline/etapy", json={"kod": "amid", "nazwa": "Amidowanie"})
    etap_id = cr.get_json()["id"]

    resp = admin_client.post(
        f"/api/pipeline/etapy/{etap_id}/warunki",
        json={
            "parametr_id": 9001,
            "operator": ">=",
            "wartosc": 6.0,
            "opis_warunku": "pH minimum",
        },
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["operator"] == ">="
    assert data["wartosc"] == 6.0
    assert data["kod"] == "ph"


def test_remove_warunek(admin_client, db):
    _seed_param(db, 9001, "ph", "pH")
    cr = admin_client.post("/api/pipeline/etapy", json={"kod": "amid", "nazwa": "Amidowanie"})
    etap_id = cr.get_json()["id"]
    w = admin_client.post(
        f"/api/pipeline/etapy/{etap_id}/warunki",
        json={"parametr_id": 9001, "operator": ">=", "wartosc": 6.0},
    ).get_json()
    wid = w["id"]

    resp = admin_client.delete(f"/api/pipeline/warunki/{wid}")
    assert resp.status_code == 200

    detail = admin_client.get(f"/api/pipeline/etapy/{etap_id}").get_json()
    assert detail["warunki"] == []


# ---------------------------------------------------------------------------
# test_add_korekta
# ---------------------------------------------------------------------------

def test_add_korekta(admin_client):
    cr = admin_client.post("/api/pipeline/etapy", json={"kod": "amid", "nazwa": "Amidowanie"})
    etap_id = cr.get_json()["id"]

    resp = admin_client.post(
        f"/api/pipeline/etapy/{etap_id}/korekty",
        json={"substancja": "NaOH", "jednostka": "kg", "wykonawca": "produkcja"},
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["substancja"] == "NaOH"
    assert data["jednostka"] == "kg"


def test_remove_korekta(admin_client):
    cr = admin_client.post("/api/pipeline/etapy", json={"kod": "amid", "nazwa": "Amidowanie"})
    etap_id = cr.get_json()["id"]
    k = admin_client.post(
        f"/api/pipeline/etapy/{etap_id}/korekty",
        json={"substancja": "NaOH"},
    ).get_json()
    kid = k["id"]

    resp = admin_client.delete(f"/api/pipeline/korekty/{kid}")
    assert resp.status_code == 200

    detail = admin_client.get(f"/api/pipeline/etapy/{etap_id}").get_json()
    assert detail["korekty"] == []


# ---------------------------------------------------------------------------
# test_pipeline_crud
# ---------------------------------------------------------------------------

def test_pipeline_crud(admin_client):
    """Add 2 stages to product, get pipeline, reorder."""
    e1 = admin_client.post("/api/pipeline/etapy", json={"kod": "amid", "nazwa": "Amidowanie"}).get_json()
    e2 = admin_client.post("/api/pipeline/etapy", json={"kod": "czwart", "nazwa": "Czwartorzędowanie"}).get_json()

    # Add both to K7 pipeline
    resp1 = admin_client.post(
        "/api/pipeline/produkt/K7/etapy",
        json={"etap_id": e1["id"], "kolejnosc": 1},
    )
    assert resp1.status_code == 201

    resp2 = admin_client.post(
        "/api/pipeline/produkt/K7/etapy",
        json={"etap_id": e2["id"], "kolejnosc": 2},
    )
    assert resp2.status_code == 201

    # Get pipeline
    resp = admin_client.get("/api/pipeline/produkt/K7")
    assert resp.status_code == 200
    pipeline = resp.get_json()
    assert len(pipeline) == 2
    assert pipeline[0]["kod"] == "amid"
    assert pipeline[1]["kod"] == "czwart"

    # Reorder: put czwart first
    resp = admin_client.put(
        "/api/pipeline/produkt/K7/reorder",
        json={"etap_ids": [e2["id"], e1["id"]]},
    )
    assert resp.status_code == 200
    pipeline = resp.get_json()
    assert pipeline[0]["kod"] == "czwart"
    assert pipeline[1]["kod"] == "amid"

    # Remove amid
    resp = admin_client.delete(f"/api/pipeline/produkt/K7/etapy/{e1['id']}")
    assert resp.status_code == 200

    pipeline = admin_client.get("/api/pipeline/produkt/K7").get_json()
    assert len(pipeline) == 1
    assert pipeline[0]["kod"] == "czwart"


# ---------------------------------------------------------------------------
# test_produkt_etap_limity
# ---------------------------------------------------------------------------

def test_produkt_etap_limity(admin_client, db):
    """Set override, get resolved limits."""
    _seed_param(db, 9001, "ph", "pH")

    e = admin_client.post("/api/pipeline/etapy", json={"kod": "amid", "nazwa": "Amidowanie"}).get_json()
    etap_id = e["id"]

    # Add catalog param with default limits
    admin_client.post(
        f"/api/pipeline/etapy/{etap_id}/parametry",
        json={"parametr_id": 9001, "kolejnosc": 1, "min_limit": 5.0, "max_limit": 9.0},
    )

    # Add to product pipeline
    admin_client.post(
        "/api/pipeline/produkt/K7/etapy",
        json={"etap_id": etap_id, "kolejnosc": 1},
    )

    # Set product override
    resp = admin_client.put(
        f"/api/pipeline/produkt/K7/etapy/{etap_id}/limity",
        json={"overrides": [{"parametr_id": 9001, "min_limit": 6.5, "max_limit": 7.5}]},
    )
    assert resp.status_code == 200
    overrides = resp.get_json()
    assert len(overrides) == 1
    assert overrides[0]["min_limit"] == 6.5

    # Get resolved limits: product override wins
    resp = admin_client.get(f"/api/pipeline/produkt/K7/etapy/{etap_id}/resolved")
    assert resp.status_code == 200
    resolved = resp.get_json()
    assert len(resolved) == 1
    assert resolved[0]["min_limit"] == 6.5
    assert resolved[0]["max_limit"] == 7.5
    assert resolved[0]["kod"] == "ph"


def test_produkt_etap_limity_fallback_to_catalog(admin_client, db):
    """Partial override: only min_limit overridden, max_limit falls back to catalog."""
    _seed_param(db, 9001, "ph", "pH")

    e = admin_client.post("/api/pipeline/etapy", json={"kod": "amid", "nazwa": "Amidowanie"}).get_json()
    etap_id = e["id"]

    admin_client.post(
        f"/api/pipeline/etapy/{etap_id}/parametry",
        json={"parametr_id": 9001, "kolejnosc": 1, "min_limit": 5.0, "max_limit": 9.0},
    )
    admin_client.post(
        "/api/pipeline/produkt/K7/etapy",
        json={"etap_id": etap_id, "kolejnosc": 1},
    )
    admin_client.put(
        f"/api/pipeline/produkt/K7/etapy/{etap_id}/limity",
        json={"overrides": [{"parametr_id": 9001, "min_limit": 6.5}]},
    )

    resolved = admin_client.get(
        f"/api/pipeline/produkt/K7/etapy/{etap_id}/resolved"
    ).get_json()
    assert resolved[0]["min_limit"] == 6.5   # override
    assert resolved[0]["max_limit"] == 9.0   # catalog fallback
