"""GET /api/parametry/<id>/usage-impact — counts for banner."""
import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed(db):
    db.execute("DELETE FROM parametry_analityczne")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (1, 'nd20', 'nD20', 'bezposredni')")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (2, 'orphan', 'orphan', 'bezposredni')")
    # 3 cert products use parametr 1, 0 use parametr 2
    for produkt in ("PROD_A", "PROD_B", "PROD_C"):
        db.execute("INSERT INTO produkty (nazwa, display_name) VALUES (?, ?)", (produkt, produkt))
        db.execute(
            "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, variant_id) VALUES (?, 1, 0, NULL)",
            (produkt,),
        )
    # 2 distinct mbr products use parametr 1 in parametry_etapy
    db.execute("INSERT INTO parametry_etapy (parametr_id, produkt, kontekst, kolejnosc) VALUES (1, 'PROD_A', 'analiza_koncowa', 0)")
    db.execute("INSERT INTO parametry_etapy (parametr_id, produkt, kontekst, kolejnosc) VALUES (1, 'PROD_X', 'analiza_koncowa', 0)")
    db.commit()


def _client(monkeypatch, db, rola="admin"):
    import mbr.db
    import mbr.parametry.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.parametry.routes, "db_session", fake_db_session)

    from mbr.app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "u", "rola": rola}
    return client


def test_usage_impact_counts_cert_and_mbr(monkeypatch, db):
    _seed(db)
    client = _client(monkeypatch, db)

    rv = client.get("/api/parametry/1/usage-impact")
    assert rv.status_code == 200
    j = rv.get_json()
    assert j["cert_products_count"] == 3
    assert j["mbr_products_count"] == 2


def test_usage_impact_zero_when_unused(monkeypatch, db):
    _seed(db)
    client = _client(monkeypatch, db)

    rv = client.get("/api/parametry/2/usage-impact")
    assert rv.status_code == 200
    j = rv.get_json()
    assert j["cert_products_count"] == 0
    assert j["mbr_products_count"] == 0


def test_usage_impact_404_for_unknown_parametr(monkeypatch, db):
    _seed(db)
    client = _client(monkeypatch, db)

    rv = client.get("/api/parametry/999/usage-impact")
    assert rv.status_code == 404
