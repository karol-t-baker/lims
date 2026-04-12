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


# ===========================================================================
# Laborant API (lab_routes.py) tests
# ===========================================================================

def _make_lab_client(monkeypatch, db):
    """Build Flask test client patching BOTH pipeline.routes and pipeline.lab_routes get_db."""
    import mbr.pipeline.routes as pipeline_routes
    import mbr.pipeline.lab_routes as lab_routes

    wrapped = _NoCloseDB(db)
    monkeypatch.setattr(pipeline_routes, "get_db", lambda: wrapped)
    monkeypatch.setattr(lab_routes, "get_db", lambda: wrapped)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "laborant1", "rola": "laborant", "imie_nazwisko": "Jan Kowalski"}
    return client


@pytest.fixture
def lab_client(monkeypatch, db):
    return _make_lab_client(monkeypatch, db)


def _seed_ebr(db, produkt="Chegina_K7"):
    """Seed minimal mbr_templates + ebr_batches. Returns (mbr_id, ebr_id)."""
    from datetime import datetime
    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, dt_utworzenia) VALUES (?, 1, 'active', ?)",
        (produkt, now),
    )
    mbr_id = cur.lastrowid
    cur2 = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start) VALUES (?, ?, ?, ?)",
        (mbr_id, f"B-{mbr_id}", f"P-{mbr_id}", now),
    )
    ebr_id = cur2.lastrowid
    db.commit()
    return mbr_id, ebr_id


def _seed_pipeline_etap(db, produkt="Chegina_K7", kolejnosc=1):
    """Seed one etap_analityczny + add to pipeline. Returns etap_id."""
    cur = db.execute(
        "INSERT INTO etapy_analityczne (kod, nazwa) VALUES ('amid_lab', 'Amidowanie Lab')"
    )
    etap_id = cur.lastrowid
    db.execute(
        "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES (?, ?, ?)",
        (produkt, etap_id, kolejnosc),
    )
    db.commit()
    return etap_id


def _seed_full_stage(db, etap_id, pid=9001, min_l=5.0, max_l=9.0):
    """Seed a parameter + gate condition + correction in etap. Returns pid."""
    db.execute(
        "INSERT OR IGNORE INTO parametry_analityczne (id, kod, label, typ) VALUES (?, ?, ?, ?)",
        (pid, "ph_t", "pH test", "bezposredni"),
    )
    db.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, min_limit, max_limit) VALUES (?, ?, 1, ?, ?)",
        (etap_id, pid, min_l, max_l),
    )
    # Gate condition: pH >= 5.0
    db.execute(
        "INSERT INTO etap_warunki (etap_id, parametr_id, operator, wartosc) VALUES (?, ?, '>=', 5.0)",
        (etap_id, pid),
    )
    # Correction catalog
    db.execute(
        "INSERT INTO etap_korekty_katalog (etap_id, substancja, jednostka) VALUES (?, 'NaOH', 'kg')",
        (etap_id,),
    )
    db.commit()
    return pid


# ---------------------------------------------------------------------------
# test_get_pipeline_lab
# ---------------------------------------------------------------------------

def test_get_pipeline_lab(lab_client, db):
    """Enriched pipeline includes session count and last status."""
    _, ebr_id = _seed_ebr(db)
    etap_id = _seed_pipeline_etap(db)

    # No sessions yet
    resp = lab_client.get(f"/api/pipeline/lab/ebr/{ebr_id}/pipeline")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert len(data) == 1
    step = data[0]
    assert step["etap_id"] == etap_id
    assert step["sesja_count"] == 0
    assert step["last_status"] is None
    assert step["last_runda"] is None

    # Create a session and check enrichment
    from mbr.pipeline import models as pm
    sesja_id = pm.create_sesja(db, ebr_id, etap_id, runda=1, laborant="lab1")
    db.commit()

    resp2 = lab_client.get(f"/api/pipeline/lab/ebr/{ebr_id}/pipeline")
    step2 = resp2.get_json()[0]
    assert step2["sesja_count"] == 1
    assert step2["last_status"] == "w_trakcie"
    assert step2["last_runda"] == 1


def test_get_pipeline_lab_not_found(lab_client):
    resp = lab_client.get("/api/pipeline/lab/ebr/9999/pipeline")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# test_get_etap_form
# ---------------------------------------------------------------------------

def test_get_etap_form(lab_client, db):
    """Stage form returns parametry, warunki, korekty_katalog."""
    _, ebr_id = _seed_ebr(db)
    etap_id = _seed_pipeline_etap(db)
    _seed_full_stage(db, etap_id)

    resp = lab_client.get(f"/api/pipeline/lab/ebr/{ebr_id}/etap/{etap_id}")
    assert resp.status_code == 200
    data = resp.get_json()

    assert "parametry" in data
    assert "warunki" in data
    assert "korekty_katalog" in data
    assert "sesje" in data
    assert "current_sesja" in data
    assert "pomiary" in data

    assert len(data["parametry"]) == 1
    assert data["parametry"][0]["kod"] == "ph_t"
    assert len(data["warunki"]) == 1
    assert len(data["korekty_katalog"]) == 1
    assert data["korekty_katalog"][0]["substancja"] == "NaOH"
    assert data["current_sesja"] is None
    assert data["pomiary"] == []


def test_get_etap_form_with_session(lab_client, db):
    """When a session exists, current_sesja and pomiary are populated."""
    _, ebr_id = _seed_ebr(db)
    etap_id = _seed_pipeline_etap(db)
    _seed_full_stage(db, etap_id)

    from mbr.pipeline import models as pm
    sesja_id = pm.create_sesja(db, ebr_id, etap_id, runda=1, laborant="lab1")
    db.commit()

    resp = lab_client.get(f"/api/pipeline/lab/ebr/{ebr_id}/etap/{etap_id}")
    data = resp.get_json()
    assert data["current_sesja"] is not None
    assert data["current_sesja"]["id"] == sesja_id
    assert len(data["sesje"]) == 1


# ---------------------------------------------------------------------------
# test_start_sesja
# ---------------------------------------------------------------------------

def test_start_sesja(lab_client, db):
    """Creates session, returns sesja_id + runda=1."""
    _, ebr_id = _seed_ebr(db)
    etap_id = _seed_pipeline_etap(db)

    resp = lab_client.post(f"/api/pipeline/lab/ebr/{ebr_id}/etap/{etap_id}/start")
    assert resp.status_code == 201
    data = resp.get_json()
    assert "sesja_id" in data
    assert data["runda"] == 1
    assert data["sesja_id"] > 0


def test_start_sesja_increments_runda(lab_client, db):
    """Second call creates runda=2."""
    _, ebr_id = _seed_ebr(db)
    etap_id = _seed_pipeline_etap(db)

    r1 = lab_client.post(f"/api/pipeline/lab/ebr/{ebr_id}/etap/{etap_id}/start").get_json()
    assert r1["runda"] == 1

    r2 = lab_client.post(f"/api/pipeline/lab/ebr/{ebr_id}/etap/{etap_id}/start").get_json()
    assert r2["runda"] == 2
    assert r2["sesja_id"] != r1["sesja_id"]


# ---------------------------------------------------------------------------
# test_save_pomiary
# ---------------------------------------------------------------------------

def test_save_pomiary(lab_client, db):
    """Saves measurements and returns gate result (passed=True for pH=7.0)."""
    _, ebr_id = _seed_ebr(db)
    etap_id = _seed_pipeline_etap(db)
    pid = _seed_full_stage(db, etap_id)

    from mbr.pipeline import models as pm
    sesja_id = pm.create_sesja(db, ebr_id, etap_id, runda=1, laborant="lab1")
    db.commit()

    resp = lab_client.post(
        f"/api/pipeline/lab/ebr/{ebr_id}/etap/{etap_id}/pomiary",
        json={"sesja_id": sesja_id, "pomiary": [{"parametr_id": pid, "wartosc": 7.0}]},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "gate" in data
    assert "pomiary" in data
    assert data["gate"]["passed"] is True
    assert data["gate"]["failures"] == []
    assert len(data["pomiary"]) == 1
    assert data["pomiary"][0]["wartosc"] == 7.0


def test_save_pomiary_gate_fail(lab_client, db):
    """Gate fails when pH value is below the gate condition (pH >= 5.0)."""
    _, ebr_id = _seed_ebr(db)
    etap_id = _seed_pipeline_etap(db)
    pid = _seed_full_stage(db, etap_id)

    from mbr.pipeline import models as pm
    sesja_id = pm.create_sesja(db, ebr_id, etap_id, runda=1, laborant="lab1")
    db.commit()

    resp = lab_client.post(
        f"/api/pipeline/lab/ebr/{ebr_id}/etap/{etap_id}/pomiary",
        json={"sesja_id": sesja_id, "pomiary": [{"parametr_id": pid, "wartosc": 3.0}]},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["gate"]["passed"] is False
    assert len(data["gate"]["failures"]) == 1
    assert data["gate"]["failures"][0]["kod"] == "ph_t"


# ---------------------------------------------------------------------------
# test_zalec_korekte
# ---------------------------------------------------------------------------

def test_zalec_korekte(lab_client, db):
    """Creates correction, returns id with 201."""
    _, ebr_id = _seed_ebr(db)
    etap_id = _seed_pipeline_etap(db)
    _seed_full_stage(db, etap_id)

    from mbr.pipeline import models as pm
    sesja_id = pm.create_sesja(db, ebr_id, etap_id, runda=1, laborant="lab1")
    db.commit()

    # Get korekta_typ_id from the seeded correction
    kat = db.execute(
        "SELECT id FROM etap_korekty_katalog WHERE etap_id = ?", (etap_id,)
    ).fetchone()
    korekta_typ_id = kat["id"]

    resp = lab_client.post(
        f"/api/pipeline/lab/ebr/{ebr_id}/korekta",
        json={"sesja_id": sesja_id, "korekta_typ_id": korekta_typ_id, "ilosc": 2.5},
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert "id" in data
    assert data["id"] > 0


def test_update_korekta_status(lab_client, db):
    """Updates correction status to 'wykonana'."""
    _, ebr_id = _seed_ebr(db)
    etap_id = _seed_pipeline_etap(db)
    _seed_full_stage(db, etap_id)

    from mbr.pipeline import models as pm
    sesja_id = pm.create_sesja(db, ebr_id, etap_id, runda=1, laborant="lab1")
    db.commit()

    kat = db.execute(
        "SELECT id FROM etap_korekty_katalog WHERE etap_id = ?", (etap_id,)
    ).fetchone()
    korekta_typ_id = kat["id"]

    kid_resp = lab_client.post(
        f"/api/pipeline/lab/ebr/{ebr_id}/korekta",
        json={"sesja_id": sesja_id, "korekta_typ_id": korekta_typ_id, "ilosc": 1.0},
    ).get_json()
    kid = kid_resp["id"]

    resp = lab_client.put(
        f"/api/pipeline/lab/ebr/{ebr_id}/korekta/{kid}/status",
        json={"status": "wykonana", "wykonawca_info": "Jan Nowak"},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}

    # Verify in DB
    row = db.execute("SELECT status, wykonawca_info FROM ebr_korekta_v2 WHERE id = ?", (kid,)).fetchone()
    assert row["status"] == "wykonana"
    assert row["wykonawca_info"] == "Jan Nowak"


# ---------------------------------------------------------------------------
# test_close_sesja
# ---------------------------------------------------------------------------

def test_close_sesja(lab_client, db):
    """Closes session with decyzja='przejscie', status becomes 'ok'."""
    _, ebr_id = _seed_ebr(db)
    etap_id = _seed_pipeline_etap(db)

    from mbr.pipeline import models as pm
    sesja_id = pm.create_sesja(db, ebr_id, etap_id, runda=1, laborant="lab1")
    db.commit()

    resp = lab_client.post(
        f"/api/pipeline/lab/ebr/{ebr_id}/etap/{etap_id}/close",
        json={"sesja_id": sesja_id, "decyzja": "przejscie"},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}

    row = db.execute("SELECT status, decyzja FROM ebr_etap_sesja WHERE id = ?", (sesja_id,)).fetchone()
    assert row["status"] == "ok"
    assert row["decyzja"] == "przejscie"


def test_close_sesja_korekta(lab_client, db):
    """Closes session with decyzja='korekta', status becomes 'oczekuje_korekty'."""
    _, ebr_id = _seed_ebr(db)
    etap_id = _seed_pipeline_etap(db)

    from mbr.pipeline import models as pm
    sesja_id = pm.create_sesja(db, ebr_id, etap_id, runda=1, laborant="lab1")
    db.commit()

    resp = lab_client.post(
        f"/api/pipeline/lab/ebr/{ebr_id}/etap/{etap_id}/close",
        json={"sesja_id": sesja_id, "decyzja": "korekta"},
    )
    assert resp.status_code == 200

    row = db.execute("SELECT status FROM ebr_etap_sesja WHERE id = ?", (sesja_id,)).fetchone()
    assert row["status"] == "oczekuje_korekty"


# ---------------------------------------------------------------------------
# Auth: lab routes require login
# ---------------------------------------------------------------------------

def test_lab_pipeline_requires_login(monkeypatch, db):
    """Unauthenticated request is redirected to login."""
    import mbr.pipeline.lab_routes as lab_routes
    wrapped = _NoCloseDB(db)
    monkeypatch.setattr(lab_routes, "get_db", lambda: wrapped)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()  # no session set

    _, ebr_id = _seed_ebr(db)
    resp = client.get(f"/api/pipeline/lab/ebr/{ebr_id}/pipeline")
    assert resp.status_code in (302, 401, 403)
