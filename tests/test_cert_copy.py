"""Tests for POST /api/cert/config/product/<src>/copy — product template deep-copy."""
import json
import sqlite3
import pytest
from contextlib import contextmanager
from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    """In-memory SQLite DB with schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _make_client(monkeypatch, db):
    """Build a Flask test client with the in-memory db monkey-patched in."""
    import mbr.db
    import mbr.certs.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.certs.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "admin", "rola": "admin", "worker_id": None}
    return client


@pytest.fixture
def client(monkeypatch, db):
    return _make_client(monkeypatch, db)


def _setup_product_with_params(db, key, display_name, params):
    """Create a product with parametry_analityczne rows + a base cert_variants + parametry_cert."""
    db.execute(
        "INSERT INTO produkty (nazwa, display_name, spec_number, cas_number, expiry_months, opinion_pl, opinion_en) "
        "VALUES (?, ?, 'P1', 'CAS-1', 12, 'opinion pl', 'opinion en')",
        (key, display_name),
    )
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
        "VALUES (?, 'base', ?, '[]', 0)",
        (key, display_name),
    )
    for idx, (kod, label) in enumerate(params):
        row = db.execute("SELECT id FROM parametry_analityczne WHERE kod=?", (kod,)).fetchone()
        if row is None:
            cur = db.execute(
                "INSERT INTO parametry_analityczne (kod, label, aktywny, typ) VALUES (?, ?, 1, 'chem')",
                (kod, label),
            )
            param_id = cur.lastrowid
        else:
            param_id = row["id"]
        db.execute(
            "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, variant_id) "
            "VALUES (?, ?, ?, '5-7', NULL)",
            (key, param_id, idx),
        )
    db.commit()


def _add_variant(db, produkt, variant_id, label):
    """Add a non-base variant to an existing product."""
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) VALUES (?, ?, ?, '[]', 1)",
        (produkt, variant_id, label),
    )
    db.commit()


def test_copy_product_copies_parameters_in_order(client, db):
    _setup_product_with_params(db, "SRC", "Source", [("ph", "pH"), ("lepkosc", "Lepkość"), ("zapach", "Zapach")])
    r = client.post("/api/cert/config/product/SRC/copy", json={"new_display_name": "TARGET"})
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()
    assert data["ok"] is True
    assert data["key"] == "TARGET"
    rows = db.execute(
        "SELECT pa.kod FROM parametry_cert pc "
        "JOIN parametry_analityczne pa ON pa.id=pc.parametr_id "
        "WHERE pc.produkt='TARGET' AND pc.variant_id IS NULL "
        "ORDER BY pc.kolejnosc"
    ).fetchall()
    assert [r["kod"] for r in rows] == ["ph", "lepkosc", "zapach"]


def test_copy_product_only_base_variant(client, db):
    _setup_product_with_params(db, "SRC2", "Source2", [("ph", "pH")])
    _add_variant(db, "SRC2", "avon", "Avon")
    r = client.post("/api/cert/config/product/SRC2/copy", json={"new_display_name": "TGT2"})
    assert r.status_code == 200
    rows = db.execute("SELECT variant_id FROM cert_variants WHERE produkt='TGT2'").fetchall()
    assert [r[0] for r in rows] == ["base"]


def test_copy_product_source_untouched(client, db):
    _setup_product_with_params(db, "SRC3", "Source3", [("ph", "pH"), ("lepkosc", "Lepkość")])
    _add_variant(db, "SRC3", "ext", "Ext")
    r = client.post("/api/cert/config/product/SRC3/copy", json={"new_display_name": "TGT3"})
    assert r.status_code == 200
    src_variants = sorted([r[0] for r in db.execute("SELECT variant_id FROM cert_variants WHERE produkt='SRC3'").fetchall()])
    src_params = [r[0] for r in db.execute(
        "SELECT pa.kod FROM parametry_cert pc JOIN parametry_analityczne pa ON pa.id=pc.parametr_id "
        "WHERE pc.produkt='SRC3' AND pc.variant_id IS NULL ORDER BY pc.kolejnosc"
    ).fetchall()]
    assert src_variants == ["base", "ext"]
    assert src_params == ["ph", "lepkosc"]


def test_copy_product_duplicate_key_409(client, db):
    _setup_product_with_params(db, "EXIST", "Exist", [("ph", "pH")])
    r = client.post("/api/cert/config/product/EXIST/copy", json={"new_display_name": "EXIST"})
    assert r.status_code == 409


def test_copy_product_invalid_chars_400(client, db):
    _setup_product_with_params(db, "SRC5", "Source5", [])
    r = client.post("/api/cert/config/product/SRC5/copy", json={"new_display_name": "Bad/Name"})
    assert r.status_code == 400


def test_copy_product_missing_src_404(client):
    r = client.post("/api/cert/config/product/NOPE/copy", json={"new_display_name": "NEW1"})
    assert r.status_code == 404


def test_copy_product_empty_display_name_400(client, db):
    _setup_product_with_params(db, "SRC6", "Source6", [])
    r = client.post("/api/cert/config/product/SRC6/copy", json={"new_display_name": "   "})
    assert r.status_code == 400
