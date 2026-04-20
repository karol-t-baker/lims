"""PR2: fast_entry_partial filters jakosciowy + zewn for open batches, shows all for completed."""

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
    import mbr.db
    import mbr.laborant.routes
    from mbr.app import app

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)
    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["user"] = {"login": "lab_test", "rola": "lab", "id": 1}
        yield c


def _seed_batch_with_mixed_params(db, status="open"):
    """Seed an EBR with 1 lab-numeric + 1 jakosciowy + 1 zewn param."""
    pid_num = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, precision) "
        "VALUES ('gestosc', 'Gęstość', 'bezposredni', 2)"
    ).lastrowid
    pid_jak = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, precision, opisowe_wartosci) "
        "VALUES ('zapach', 'Zapach', 'jakosciowy', 0, ?)",
        (_json.dumps(["charakterystyczny"]),),
    ).lastrowid
    pid_zewn = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, precision) "
        "VALUES ('siarka', 'Siarka', 'bezposredni', 3)"
    ).lastrowid

    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('P1', 'P1')")

    # etapy_analityczne (not etapy_katalog)
    eid = db.execute(
        "INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu) VALUES ('e1', 'Etap 1', 'jednorazowy')"
    ).lastrowid

    db.execute(
        "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) "
        "VALUES ('P1', ?, 1)",
        (eid,),
    )

    # etap_parametry: all three params in catalog
    for pid in [pid_num, pid_jak, pid_zewn]:
        db.execute(
            "INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) "
            "VALUES (?, ?, 1)",
            (eid, pid),
        )

    # produkt_etap_limity: num + jak go to lab group; zewn goes to zewn group
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
        "dla_szarzy, dla_zbiornika, grupa) VALUES ('P1', ?, ?, 1, 0, 'lab')",
        (eid, pid_num),
    )
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
        "dla_szarzy, dla_zbiornika, grupa) VALUES ('P1', ?, ?, 1, 0, 'lab')",
        (eid, pid_jak),
    )
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
        "dla_szarzy, dla_zbiornika, grupa) VALUES ('P1', ?, ?, 1, 0, 'zewn')",
        (eid, pid_zewn),
    )

    mbr_id = db.execute(
        "INSERT INTO mbr_templates (produkt, status, parametry_lab, etapy_json, dt_utworzenia) "
        "VALUES ('P1', 'active', '{}', '[]', '2026-04-20')"
    ).lastrowid
    ebr_id = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, nr_amidatora, "
        "nr_mieszalnika, wielkosc_szarzy_kg, dt_start, operator, typ, status) "
        "VALUES (?, 'P1__1', '1', 'A', 'M', 100, '2026-04-20', 'lab', 'szarza', ?)",
        (mbr_id, status),
    ).lastrowid
    db.commit()
    return ebr_id


def test_entry_partial_hides_jakosciowy_and_zewn_for_open_batch(client, db):
    ebr_id = _seed_batch_with_mixed_params(db, status="open")
    r = client.get(f"/laborant/ebr/{ebr_id}/partial")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "gestosc" in html
    assert "zapach" not in html
    assert "siarka" not in html


def test_entry_partial_shows_all_for_completed_batch(client, db):
    ebr_id = _seed_batch_with_mixed_params(db, status="completed")
    r = client.get(f"/laborant/ebr/{ebr_id}/partial")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "gestosc" in html
    assert "zapach" in html
    assert "siarka" in html
