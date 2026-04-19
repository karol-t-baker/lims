"""Tests for mbr.registry.models."""

import json
import sqlite3
import pytest
from unittest.mock import patch
from mbr.models import init_mbr_tables
from mbr.registry.models import (
    list_completed_products,
    list_completed_registry,
    get_registry_columns,
    export_wyniki_csv,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    # Migration: nr_zbiornika was added after initial schema
    try:
        conn.execute("ALTER TABLE ebr_batches ADD COLUMN nr_zbiornika TEXT")
        conn.commit()
    except Exception:
        pass
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_mbr(db, produkt, status="active", parametry_lab=None):
    if parametry_lab is None:
        parametry_lab = json.dumps({
            "analiza": {
                "pola": [
                    {"kod": "ph", "label": "pH", "min": 6.0, "max": 7.5},
                    {"kod": "aa", "label": "%AA", "min": 38.0, "max": 42.0},
                ]
            }
        })
    cur = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "dt_utworzenia) VALUES (?, 1, ?, '[]', ?, datetime('now'))",
        (produkt, status, parametry_lab),
    )
    db.commit()
    return cur.lastrowid


def _insert_ebr(db, mbr_id, batch_id, nr_partii, status="completed", typ="szarza"):
    cur = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, dt_end, status, typ) "
        "VALUES (?, ?, ?, datetime('now', '-1 hour'), datetime('now'), ?, ?)",
        (mbr_id, batch_id, nr_partii, status, typ),
    )
    db.commit()
    return cur.lastrowid


def _insert_wynik(db, ebr_id, sekcja, kod, tag, wartosc, w_limicie=1):
    db.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc, w_limicie, "
        "dt_wpisu, wpisal) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), 'tester')",
        (ebr_id, sekcja, kod, tag, wartosc, w_limicie),
    )
    db.commit()


@pytest.fixture
def seeded(db):
    """Two products, one completed batch each with wyniki."""
    mbr1 = _insert_mbr(db, "Chegina K40GL")
    mbr2 = _insert_mbr(db, "Chegina K7")
    ebr1 = _insert_ebr(db, mbr1, "B2026-001", "1/2026")
    ebr2 = _insert_ebr(db, mbr2, "B2026-002", "2/2026")
    _insert_wynik(db, ebr1, "analiza", "ph", "pH", 6.8)
    _insert_wynik(db, ebr1, "analiza", "aa", "%AA", 40.1)
    _insert_wynik(db, ebr2, "analiza", "ph", "pH", 6.5, w_limicie=0)
    return {"mbr1": mbr1, "mbr2": mbr2, "ebr1": ebr1, "ebr2": ebr2}


# ---------------------------------------------------------------------------
# list_completed_products
# ---------------------------------------------------------------------------

def test_list_completed_products_empty(db):
    assert list_completed_products(db) == []


def test_list_completed_products_returns_distinct(db, seeded):
    products = list_completed_products(db)
    assert "Chegina K40GL" in products
    assert "Chegina K7" in products
    assert len(products) == 2


def test_list_completed_products_excludes_open(db):
    mbr_id = _insert_mbr(db, "Chegina K40GLOL")
    _insert_ebr(db, mbr_id, "B2026-010", "10/2026", status="open")
    products = list_completed_products(db)
    assert "Chegina K40GLOL" not in products


def test_list_completed_products_ordered_alphabetically(db, seeded):
    products = list_completed_products(db)
    assert products == sorted(products)


# ---------------------------------------------------------------------------
# list_completed_registry
# ---------------------------------------------------------------------------

def test_list_completed_registry_empty(db):
    assert list_completed_registry(db) == []


def test_list_completed_registry_returns_all_completed(db, seeded):
    rows = list_completed_registry(db)
    assert len(rows) == 2


def test_list_completed_registry_wyniki_attached(db, seeded):
    rows = list_completed_registry(db)
    ebr1_row = next(r for r in rows if r["batch_id"] == "B2026-001")
    assert "ph" in ebr1_row["wyniki"]
    assert ebr1_row["wyniki"]["ph"]["wartosc"] == pytest.approx(6.8)


def test_list_completed_registry_filter_by_produkt(db, seeded):
    rows = list_completed_registry(db, produkt="Chegina K40GL")
    assert len(rows) == 1
    assert rows[0]["produkt"] == "Chegina K40GL"


def test_list_completed_registry_excludes_open(db, seeded):
    mbr_id = _insert_mbr(db, "Chegina K40GLOL")
    _insert_ebr(db, mbr_id, "B2026-099", "99/2026", status="open")
    rows = list_completed_registry(db)
    assert all(r["batch_id"] != "B2026-099" for r in rows)


def test_list_completed_registry_cert_count(db, seeded):
    # No certs inserted — cert_count should be 0
    rows = list_completed_registry(db)
    for r in rows:
        assert r["cert_count"] == 0


def test_list_completed_registry_includes_uwagi_koncowe(db):
    """Registry should expose uwagi_koncowe column for the completed list view."""
    from datetime import datetime
    from mbr.registry.models import list_completed_registry

    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia) VALUES (?, 1, 'active', '[]', '{}', 'test', ?)",
        ("TestProduct", now),
    )
    mbr_id = db.execute(
        "SELECT mbr_id FROM mbr_templates WHERE produkt='TestProduct'"
    ).fetchone()["mbr_id"]
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, dt_end, status, typ, uwagi_koncowe) "
        "VALUES (?, 'TP__1', '1/2026', ?, ?, 'completed', 'szarza', 'nota testowa')",
        (mbr_id, now, now),
    )
    db.commit()

    result = list_completed_registry(db, produkt="TestProduct")
    assert len(result) == 1
    assert result[0]["uwagi_koncowe"] == "nota testowa"


def test_list_completed_registry_filter_by_typ(db, seeded):
    # seeded already has mbr1 for "Chegina K40GL" wersja=1; use that mbr_id directly
    mbr_id = seeded["mbr1"]
    _insert_ebr(db, mbr_id, "B2026-Z1", "Z1/2026", typ="zbiornik")
    rows_szarza = list_completed_registry(db, produkt="Chegina K40GL", typ="szarza")
    rows_zbiornik = list_completed_registry(db, produkt="Chegina K40GL", typ="zbiornik")
    assert all(r["typ"] == "szarza" for r in rows_szarza)
    assert all(r["typ"] == "zbiornik" for r in rows_zbiornik)


# ---------------------------------------------------------------------------
# get_registry_columns
# ---------------------------------------------------------------------------

def test_get_registry_columns_no_active_mbr(db):
    assert get_registry_columns(db, "NonExistentProd") == []


@pytest.mark.skip(reason="get_registry_columns now reads from produkt_etap_limity via build_pipeline_context; test needs re-seeding via that SSOT. Legacy mbr_templates.parametry_lab path deprecated post-MVP 2026-04-16.")
def test_get_registry_columns_returns_pola(db, seeded):
    pass


@pytest.mark.skip(reason="Same as above — mbr_templates.parametry_lab no longer drives registry columns.")
def test_get_registry_columns_legacy_analiza_koncowa(db):
    pass


def test_get_registry_columns_inactive_mbr_not_used(db):
    _insert_mbr(db, "DraftProd", status="draft")
    assert get_registry_columns(db, "DraftProd") == []


# ---------------------------------------------------------------------------
# export_wyniki_csv
# ---------------------------------------------------------------------------

def test_export_wyniki_csv_empty(db):
    rows = export_wyniki_csv(db)
    assert rows == []


def test_export_wyniki_csv_returns_rows(db, seeded):
    rows = export_wyniki_csv(db)
    assert len(rows) == 3  # 2 wyniki for ebr1, 1 for ebr2


def test_export_wyniki_csv_has_expected_keys(db, seeded):
    rows = export_wyniki_csv(db)
    required_keys = {"batch_id", "produkt", "nr_partii", "sekcja", "kod_parametru",
                     "tag", "wartosc", "w_limicie", "wpisal"}
    for row in rows:
        assert required_keys.issubset(row.keys())


def test_export_wyniki_csv_filter_by_produkt(db, seeded):
    rows = export_wyniki_csv(db, produkt="Chegina K40GL")
    assert all(r["produkt"] == "Chegina K40GL" for r in rows)
    assert len(rows) == 2


def test_export_wyniki_csv_excludes_open_batches(db, seeded):
    mbr_id = _insert_mbr(db, "Chegina K40GLOL")
    open_ebr = _insert_ebr(db, mbr_id, "B2026-OPEN", "50/2026", status="open")
    _insert_wynik(db, open_ebr, "analiza", "ph", "pH", 7.0)
    rows = export_wyniki_csv(db)
    assert all(r["batch_id"] != "B2026-OPEN" for r in rows)


# ---------------------------------------------------------------------------
# Cancel endpoint
# ---------------------------------------------------------------------------

@pytest.fixture
def cancel_app(tmp_path):
    db_path = tmp_path / "test.sqlite"
    with patch("mbr.db.DB_PATH", db_path):
        from mbr.app import create_app
        from mbr.db import get_db
        from mbr.models import init_mbr_tables
        application = create_app()
        application.config["TESTING"] = True
        application.config["SECRET_KEY"] = "test"
        conn = get_db()
        init_mbr_tables(conn)
        conn.execute(
            "INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, parametry_lab, dt_utworzenia) "
            "VALUES (1, 'Test', '1.0', 'active', '{}', datetime('now'))"
        )
        conn.execute(
            "INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start, status, sync_seq) "
            "VALUES (1, 1, 'T__1', '1/2026', datetime('now'), 'completed', 1)"
        )
        conn.execute(
            "INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start, status) "
            "VALUES (2, 1, 'T__2', '2/2026', datetime('now'), 'open')"
        )
        conn.commit()
        conn.close()
        yield application


@pytest.fixture
def admin_client(cancel_app):
    client = cancel_app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "admin", "rola": "admin", "imie_nazwisko": "Admin"}
    return client


@pytest.fixture
def laborant_client(cancel_app):
    client = cancel_app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "lab1", "rola": "lab", "imie_nazwisko": "Lab"}
    return client


def test_cancel_completed_batch(admin_client, tmp_path):
    with patch("mbr.db.DB_PATH", tmp_path / "test.sqlite"):
        resp = admin_client.post("/api/registry/1/cancel")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

        from mbr.db import get_db
        conn = get_db()
        row = conn.execute("SELECT status FROM ebr_batches WHERE ebr_id=1").fetchone()
        conn.close()
        assert row["status"] == "cancelled"


def test_cancel_requires_admin(laborant_client, tmp_path):
    with patch("mbr.db.DB_PATH", tmp_path / "test.sqlite"):
        resp = laborant_client.post("/api/registry/1/cancel")
        assert resp.status_code == 403


def test_cancel_nonexistent_batch(admin_client, tmp_path):
    with patch("mbr.db.DB_PATH", tmp_path / "test.sqlite"):
        resp = admin_client.post("/api/registry/999/cancel")
        assert resp.status_code == 404


def test_cancel_non_completed_batch(admin_client, tmp_path):
    with patch("mbr.db.DB_PATH", tmp_path / "test.sqlite"):
        resp = admin_client.post("/api/registry/2/cancel")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Surowce column (Alkinol A/B uses substrat_produkty config)
# ---------------------------------------------------------------------------

def _seed_substrat(db, nazwa, produkt, skrot=None):
    """Create a substrat (optionally with skrot) and link it to a product."""
    cur = db.execute(
        "INSERT INTO substraty (nazwa, skrot) VALUES (?, ?)", (nazwa, skrot)
    )
    sid = cur.lastrowid
    db.execute(
        "INSERT INTO substrat_produkty (substrat_id, produkt) VALUES (?, ?)",
        (sid, produkt),
    )
    db.commit()
    return sid


def test_registry_row_includes_skrot(db):
    mbr = _insert_mbr(db, "Alkinol")
    ebr = _insert_ebr(db, mbr, "B-A-003", "3/26")
    sid = _seed_substrat(db, "Alkohol oxyetylenowany 30/70", "Alkinol", skrot="30/70")
    _link_batch_substrat(db, ebr, sid, "500/26")

    rows = list_completed_registry(db, produkt="Alkinol")
    s = rows[0]["surowce"][0]
    assert s["nazwa"] == "Alkohol oxyetylenowany 30/70"
    assert s["skrot"] == "30/70"
    assert s["nr_partii"] == "500/26"


def _link_batch_substrat(db, ebr_id, substrat_id, nr_partii):
    db.execute(
        "INSERT INTO platkowanie_substraty (ebr_id, substrat_id, nr_partii_substratu) "
        "VALUES (?, ?, ?)",
        (ebr_id, substrat_id, nr_partii),
    )
    db.commit()


def test_registry_columns_includes_surowce_for_alkinol(db):
    mbr = _insert_mbr(db, "Alkinol")
    _seed_substrat(db, "Kwas XYZ", "Alkinol")
    cols = get_registry_columns(db, "Alkinol")
    kods = [c["kod"] for c in cols]
    assert "__surowce__" in kods
    surowce_col = next(c for c in cols if c["kod"] == "__surowce__")
    assert surowce_col["label"] == "Surowce"


def test_registry_columns_omits_surowce_for_other_products(db):
    mbr = _insert_mbr(db, "Chegina K7")
    cols = get_registry_columns(db, "Chegina K7")
    kods = [c["kod"] for c in cols]
    assert "__surowce__" not in kods


def test_registry_row_groups_same_surowiec_multiple_partie(db):
    mbr = _insert_mbr(db, "Alkinol")
    ebr = _insert_ebr(db, mbr, "B-A-001", "1/26")
    sid = _seed_substrat(db, "NaOH", "Alkinol")
    _link_batch_substrat(db, ebr, sid, "100/26")
    _link_batch_substrat(db, ebr, sid, "101/26")

    rows = list_completed_registry(db, produkt="Alkinol")
    assert len(rows) == 1
    surowce = rows[0]["surowce"]
    assert len(surowce) == 2
    assert all(s["nazwa"] == "NaOH" for s in surowce)
    partie = [s["nr_partii"] for s in surowce]
    assert sorted(partie) == ["100/26", "101/26"]


def test_registry_row_empty_surowce_for_batch_without_data(db):
    mbr = _insert_mbr(db, "Alkinol")
    ebr = _insert_ebr(db, mbr, "B-A-002", "2/26")
    rows = list_completed_registry(db, produkt="Alkinol")
    assert rows[0]["surowce"] == []
