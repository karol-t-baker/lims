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
