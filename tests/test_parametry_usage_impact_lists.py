"""GET /api/parametry/<id>/usage-impact returns product lists alongside counts."""
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
    for produkt, dn in [("PROD_A", "Produkt A"), ("PROD_B", "Produkt B")]:
        db.execute("INSERT INTO produkty (nazwa, display_name) VALUES (?, ?)", (produkt, dn))
        db.execute("INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, variant_id) VALUES (?, 1, 0, NULL)", (produkt,))
    db.execute("INSERT INTO parametry_etapy (parametr_id, produkt, kontekst, kolejnosc) VALUES (1, 'PROD_A', 'analiza_koncowa', 0)")
    db.execute("INSERT INTO parametry_etapy (parametr_id, produkt, kontekst, kolejnosc) VALUES (1, 'PROD_A', 'sulfonowanie', 1)")
    db.execute("INSERT INTO parametry_etapy (parametr_id, produkt, kontekst, kolejnosc) VALUES (1, 'PROD_C', 'analiza_koncowa', 0)")
    db.commit()


def _client(monkeypatch, db):
    import mbr.db, mbr.parametry.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.parametry.routes, "db_session", fake_db_session)

    from mbr.app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "admin", "rola": "admin"}
    return client


def test_usage_impact_includes_cert_products_list(monkeypatch, db):
    _seed(db)
    client = _client(monkeypatch, db)

    rv = client.get("/api/parametry/1/usage-impact")
    assert rv.status_code == 200
    j = rv.get_json()
    assert j["cert_products_count"] == 2
    assert "cert_products" in j
    assert sorted(p["key"] for p in j["cert_products"]) == ["PROD_A", "PROD_B"]
    a = next(p for p in j["cert_products"] if p["key"] == "PROD_A")
    assert a["display_name"] == "Produkt A"


def test_usage_impact_includes_mbr_products_list_with_stages(monkeypatch, db):
    _seed(db)
    client = _client(monkeypatch, db)

    rv = client.get("/api/parametry/1/usage-impact")
    j = rv.get_json()
    assert j["mbr_products_count"] == 2  # PROD_A + PROD_C
    assert j["mbr_bindings_count"] == 3  # PROD_A×2 + PROD_C×1
    by_key = {p["key"]: p for p in j["mbr_products"]}
    assert sorted(by_key["PROD_A"]["stages"]) == ["analiza_koncowa", "sulfonowanie"]
    assert by_key["PROD_C"]["stages"] == ["analiza_koncowa"]


def test_usage_impact_empty_lists_for_unused_param(monkeypatch, db):
    _seed(db)
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (2, 'orphan', 'orphan', 'bezposredni')")
    db.commit()
    client = _client(monkeypatch, db)

    rv = client.get("/api/parametry/2/usage-impact")
    j = rv.get_json()
    assert j["cert_products_count"] == 0
    assert j["mbr_products_count"] == 0
    assert j["cert_products"] == []
    assert j["mbr_products"] == []
    assert j["mbr_bindings_count"] == 0


def test_usage_impact_includes_formula_override(monkeypatch, db):
    """mbr_products items have formula_override field reflecting parametry_etapy.formula
    in analiza_koncowa kontekst (hardcoded for current obliczeniowy/srednia use case)."""
    db.execute("DELETE FROM parametry_analityczne")
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, formula) "
        "VALUES (1, 'sa', 'SA', 'obliczeniowy', 'sm - nacl - sa_bias')"
    )
    db.execute("INSERT OR IGNORE INTO produkty (nazwa, display_name) VALUES ('Cheminox_K', 'Cheminox K')")
    db.execute("INSERT OR IGNORE INTO produkty (nazwa, display_name) VALUES ('Chegina_K7', 'Chegina K7')")
    # Cheminox_K has SA in analiza_koncowa with formula override
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, produkt, kontekst, kolejnosc, formula) "
        "VALUES (1, 'Cheminox_K', 'analiza_koncowa', 0, 'sm')"
    )
    # Chegina_K7 has SA in analiza_koncowa WITHOUT override
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, produkt, kontekst, kolejnosc) "
        "VALUES (1, 'Chegina_K7', 'analiza_koncowa', 0)"
    )
    db.commit()
    client = _client(monkeypatch, db)

    rv = client.get("/api/parametry/1/usage-impact")
    j = rv.get_json()
    by_key = {p["key"]: p for p in j["mbr_products"]}
    assert by_key["Cheminox_K"]["formula_override"] == "sm"
    assert by_key["Chegina_K7"]["formula_override"] is None
