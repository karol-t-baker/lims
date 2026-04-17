"""Tests for admin batch metadata editor: PATCH /api/admin/ebr/<id>/meta."""

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
    import mbr.admin.routes
    import mbr.laborant.routes
    import mbr.technolog.routes
    import mbr.certs.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.technolog.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.certs.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": rola, "worker_id": None}
    return client


def _seed_batch(db, ebr_id=1, typ="szarza", nastaw=6500):
    db.execute(
        """INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia)
           VALUES (1, 'Chegina_K7', 1, '2026-01-01')"""
    )
    db.execute(
        """INSERT INTO ebr_batches
           (ebr_id, mbr_id, batch_id, nr_partii, nr_amidatora, nr_mieszalnika,
            nastaw, wielkosc_szarzy_kg, dt_start, status, typ)
           VALUES (?, 1, 'B-1', '1/2026', 'A-1', 'M-1', ?, ?, '2026-04-17', 'open', ?)""",
        (ebr_id, nastaw, nastaw, typ),
    )
    db.commit()


@pytest.fixture
def admin_client(monkeypatch, db):
    _seed_batch(db)
    return _make_client(monkeypatch, db, rola="admin")


@pytest.fixture
def lab_client(monkeypatch, db):
    _seed_batch(db)
    return _make_client(monkeypatch, db, rola="lab")


def test_admin_patch_meta_updates_all_fields(admin_client, db):
    resp = admin_client.patch(
        "/api/admin/ebr/1/meta",
        json={"nastaw": 7000, "typ": "zbiornik",
              "nr_amidatora": "A-99", "nr_mieszalnika": "M-99"},
    )
    assert resp.status_code == 200
    row = db.execute(
        "SELECT nastaw, typ, nr_amidatora, nr_mieszalnika FROM ebr_batches WHERE ebr_id=1"
    ).fetchone()
    assert row["nastaw"] == 7000
    assert row["typ"] == "zbiornik"
    assert row["nr_amidatora"] == "A-99"
    assert row["nr_mieszalnika"] == "M-99"


def test_admin_patch_meta_partial_update(admin_client, db):
    """Only provided fields change; omitted ones stay untouched."""
    resp = admin_client.patch(
        "/api/admin/ebr/1/meta", json={"nr_mieszalnika": "M-XX"},
    )
    assert resp.status_code == 200
    row = db.execute(
        "SELECT nastaw, typ, nr_amidatora, nr_mieszalnika FROM ebr_batches WHERE ebr_id=1"
    ).fetchone()
    assert row["nr_mieszalnika"] == "M-XX"
    assert row["nastaw"] == 6500
    assert row["typ"] == "szarza"
    assert row["nr_amidatora"] == "A-1"


def test_admin_patch_meta_rejects_invalid_typ(admin_client, db):
    resp = admin_client.patch(
        "/api/admin/ebr/1/meta", json={"typ": "bzdura"},
    )
    assert resp.status_code == 400
    row = db.execute("SELECT typ FROM ebr_batches WHERE ebr_id=1").fetchone()
    assert row["typ"] == "szarza"


def test_admin_patch_meta_rejects_negative_nastaw(admin_client, db):
    resp = admin_client.patch(
        "/api/admin/ebr/1/meta", json={"nastaw": -50},
    )
    assert resp.status_code == 400


def test_admin_patch_meta_404_when_ebr_missing(admin_client, db):
    resp = admin_client.patch(
        "/api/admin/ebr/9999/meta", json={"nastaw": 7000},
    )
    assert resp.status_code == 404


def test_admin_patch_meta_forbidden_for_lab(lab_client, db):
    resp = lab_client.patch(
        "/api/admin/ebr/1/meta", json={"nastaw": 7000},
    )
    assert resp.status_code == 403


def test_admin_patch_meta_writes_audit_diff(admin_client, db):
    admin_client.patch(
        "/api/admin/ebr/1/meta",
        json={"nastaw": 7200, "nr_mieszalnika": "M-42"},
    )
    audit_row = db.execute(
        "SELECT diff_json, event_type, entity_type, entity_id "
        "FROM audit_log WHERE event_type='ebr.batch.updated' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert audit_row is not None
    assert audit_row["entity_type"] == "ebr"
    assert audit_row["entity_id"] == 1
    import json
    diff = json.loads(audit_row["diff_json"])
    changed = {d["pole"] for d in diff}
    assert changed == {"nastaw", "nr_mieszalnika"}


def test_admin_patch_meta_noop_when_nothing_changes(admin_client, db):
    """Sending the current values shouldn't write an audit row."""
    before = db.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
    resp = admin_client.patch(
        "/api/admin/ebr/1/meta",
        json={"nastaw": 6500, "typ": "szarza", "nr_amidatora": "A-1", "nr_mieszalnika": "M-1"},
    )
    assert resp.status_code == 200
    after = db.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
    assert after == before, "no audit row when nothing actually changed"


# ─── DELETE endpoint ──────────────────────────────────────────────────────────

def _seed_batch_with_children(db, ebr_id=2, status="open"):
    """Seed a batch plus a sesja + pomiar + korekta + wynik + uwagi row so we
    can assert the cascade wipes everything."""
    db.execute(
        "INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (777, 'e_test', 'Test', 'jednorazowy')"
    )
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (777, 'p_test', 'p', 'bezposredni')"
    )
    db.execute(
        "INSERT INTO etap_korekty_katalog (id, etap_id, substancja, jednostka) VALUES (777, 777, 'X', 'kg')"
    )
    db.execute(
        "INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, nr_amidatora, nr_mieszalnika, "
        "nastaw, wielkosc_szarzy_kg, dt_start, status, typ) "
        "VALUES (?, 1, 'B-2', '272/2026', 'A-2', 'M-2', 6500, 6500, '2026-04-17', ?, 'szarza')",
        (ebr_id, status),
    )
    db.execute(
        "INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status) VALUES (777, ?, 777, 1, 'zamkniety')",
        (ebr_id,),
    )
    db.execute(
        "INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, dt_wpisu, wpisal) "
        "VALUES (777, 777, 1.0, '2026-04-17', 'JK')"
    )
    db.execute(
        "INSERT INTO ebr_korekta_v2 (sesja_id, korekta_typ_id, ilosc) VALUES (777, 777, 5.0)"
    )
    db.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc, dt_wpisu, wpisal) "
        "VALUES (?, 'analiza_koncowa', 'p_test', 'p', 1.0, '2026-04-17', 'JK')",
        (ebr_id,),
    )
    db.execute(
        "INSERT INTO ebr_uwagi_history (ebr_id, dt, autor, tekst, action) "
        "VALUES (?, '2026-04-17', 'JK', 'test', 'create')",
        (ebr_id,),
    )
    db.commit()


def test_admin_delete_batch_cascades_and_frees_nr_partii(admin_client, db):
    _seed_batch_with_children(db, ebr_id=2, status="open")
    resp = admin_client.delete("/api/admin/ebr/2")
    assert resp.status_code == 200
    assert db.execute("SELECT 1 FROM ebr_batches WHERE ebr_id=2").fetchone() is None
    assert db.execute("SELECT 1 FROM ebr_etap_sesja WHERE ebr_id=2").fetchone() is None
    assert db.execute("SELECT 1 FROM ebr_pomiar WHERE sesja_id=777").fetchone() is None
    assert db.execute("SELECT 1 FROM ebr_korekta_v2 WHERE sesja_id=777").fetchone() is None
    assert db.execute("SELECT 1 FROM ebr_wyniki WHERE ebr_id=2").fetchone() is None
    assert db.execute("SELECT 1 FROM ebr_uwagi_history WHERE ebr_id=2").fetchone() is None
    # nr_partii is free for a new batch with the same number
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, typ) "
        "VALUES (1, 'B-2-NEW', '272/2026', '2026-04-18', 'open', 'szarza')"
    )
    db.commit()  # no IntegrityError raised = nr_partii reusable


def test_admin_delete_batch_rejects_completed(admin_client, db):
    _seed_batch_with_children(db, ebr_id=3, status="completed")
    resp = admin_client.delete("/api/admin/ebr/3")
    assert resp.status_code == 400
    # Still there — completed batches require cancel first
    assert db.execute("SELECT 1 FROM ebr_batches WHERE ebr_id=3").fetchone() is not None


def test_admin_delete_batch_404_missing(admin_client, db):
    resp = admin_client.delete("/api/admin/ebr/9999")
    assert resp.status_code == 404


def test_admin_delete_batch_forbidden_for_lab(lab_client, db):
    _seed_batch_with_children(db, ebr_id=4, status="open")
    resp = lab_client.delete("/api/admin/ebr/4")
    assert resp.status_code == 403
    assert db.execute("SELECT 1 FROM ebr_batches WHERE ebr_id=4").fetchone() is not None


def test_admin_delete_batch_writes_audit(admin_client, db):
    _seed_batch_with_children(db, ebr_id=5, status="open")
    admin_client.delete("/api/admin/ebr/5")
    row = db.execute(
        "SELECT event_type, entity_type, entity_id, entity_label, payload_json "
        "FROM audit_log WHERE event_type='ebr.batch.deleted' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["entity_type"] == "ebr"
    assert row["entity_id"] == 5
    assert row["entity_label"] == "Szarża 272/2026"
    import json
    payload = json.loads(row["payload_json"])
    assert payload["nr_partii"] == "272/2026"
    assert payload["status"] == "open"
