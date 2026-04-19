"""Regression: PUT /api/parametry/sa-bias must NOT mutate NULL-produkt
global row when no per-product binding exists — it must create a new
per-product binding instead."""

import json
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


def _seed_global_sa_binding(db, formula="sm - nacl - 0.5"):
    """Seed parametry_analityczne + global NULL-produkt parametry_etapy row."""
    cur = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, skrot, typ, aktywny, formula) "
        "VALUES ('sa', 'SA', 'SA', 'chem', 1, ?)",
        (formula,),
    )
    pa_id = cur.lastrowid
    db.execute(
        "INSERT INTO parametry_etapy (produkt, kontekst, parametr_id, sa_bias, formula) "
        "VALUES (NULL, 'analiza_koncowa', ?, 0.5, NULL)",
        (pa_id,),
    )
    # Minimal MBR templates for both products (route rebuild needs them)
    for produkt in ("Chegina_K7", "Chegina_K40GL"):
        db.execute(
            "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
            "dt_utworzenia) VALUES (?, 1, 'active', '[]', '{}', datetime('now'))",
            (produkt,),
        )
    db.commit()
    return pa_id


def _make_client(monkeypatch, db):
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
        sess["user"] = {"login": "tester", "rola": "lab", "worker_id": None}
        sess["shift_workers"] = []
    return c


@pytest.fixture
def client(monkeypatch, db):
    return _make_client(monkeypatch, db)


def test_sa_bias_change_does_not_mutate_global_row(client, db):
    """Laborant changes SA bias for product A → global NULL-produkt row
    must remain untouched (so product B still reads the original bias)."""
    pa_id = _seed_global_sa_binding(db, formula="sm - nacl - 0.5")

    # Snapshot global row state BEFORE the PUT
    global_before = db.execute(
        "SELECT id, sa_bias, formula FROM parametry_etapy "
        "WHERE produkt IS NULL AND parametr_id=?",
        (pa_id,),
    ).fetchone()
    assert global_before["sa_bias"] == 0.5

    # Laborant updates bias for product A
    resp = client.put(
        "/api/parametry/sa-bias",
        json={"kod": "sa", "produkt": "Chegina_K7", "sa_bias": 0.8},
    )
    assert resp.status_code == 200

    # Global row UNCHANGED
    global_after = db.execute(
        "SELECT sa_bias, formula FROM parametry_etapy WHERE id=?",
        (global_before["id"],),
    ).fetchone()
    assert global_after["sa_bias"] == 0.5, (
        "Global NULL-produkt sa_bias should not change — it would leak to other products"
    )
    assert global_after["formula"] == global_before["formula"]


def test_sa_bias_change_creates_per_product_binding(client, db):
    """When no per-product binding exists, PUT must INSERT a new per-product row."""
    pa_id = _seed_global_sa_binding(db, formula="sm - nacl - 0.5")

    client.put(
        "/api/parametry/sa-bias",
        json={"kod": "sa", "produkt": "Chegina_K7", "sa_bias": 0.8},
    )

    per_product = db.execute(
        "SELECT sa_bias, formula FROM parametry_etapy "
        "WHERE produkt='Chegina_K7' AND parametr_id=? AND kontekst='analiza_koncowa'",
        (pa_id,),
    ).fetchone()
    assert per_product is not None
    assert per_product["sa_bias"] == 0.8


def test_sa_bias_existing_per_product_binding_gets_updated(client, db):
    """If per-product binding already exists, update it (not create another)."""
    pa_id = _seed_global_sa_binding(db, formula="sm - nacl - 0.5")
    db.execute(
        "INSERT INTO parametry_etapy (produkt, kontekst, parametr_id, sa_bias, formula) "
        "VALUES ('Chegina_K7', 'analiza_koncowa', ?, 0.7, 'sm - nacl - 0.7')",
        (pa_id,),
    )
    db.commit()

    client.put(
        "/api/parametry/sa-bias",
        json={"kod": "sa", "produkt": "Chegina_K7", "sa_bias": 0.9},
    )

    rows = db.execute(
        "SELECT sa_bias FROM parametry_etapy "
        "WHERE produkt='Chegina_K7' AND parametr_id=? AND kontekst='analiza_koncowa'",
        (pa_id,),
    ).fetchall()
    assert len(rows) == 1, "Must UPDATE existing per-product row, not INSERT another"
    assert rows[0]["sa_bias"] == 0.9


def test_sa_bias_other_products_unaffected(client, db):
    """Product A's bias change does not affect product B that also relied on global."""
    pa_id = _seed_global_sa_binding(db, formula="sm - nacl - 0.5")

    client.put(
        "/api/parametry/sa-bias",
        json={"kod": "sa", "produkt": "Chegina_K7", "sa_bias": 0.8},
    )

    # Product B has no per-product row → still reads global (0.5)
    b_row = db.execute(
        "SELECT sa_bias FROM parametry_etapy "
        "WHERE produkt='Chegina_K40GL' AND parametr_id=?",
        (pa_id,),
    ).fetchone()
    assert b_row is None, "Product B should have no per-product row created"

    # Global unchanged
    global_row = db.execute(
        "SELECT sa_bias FROM parametry_etapy "
        "WHERE produkt IS NULL AND parametr_id=?",
        (pa_id,),
    ).fetchone()
    assert global_row["sa_bias"] == 0.5, "Global row must be untouched"
