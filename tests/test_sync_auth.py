"""Shared-secret token auth on COA sync endpoints (/api/completed, /api/admin/db-snapshot)."""

import os
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


@pytest.fixture
def client(monkeypatch, db, tmp_path):
    import mbr.db
    import mbr.admin.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.routes, "db_session", fake_db_session)

    # Point DB_PATH at a non-empty temp file so /api/admin/db-snapshot can send_file.
    fake_db = tmp_path / "fake.sqlite"
    fake_db.write_bytes(b"SQLite fake")
    monkeypatch.setattr(mbr.db, "DB_PATH", fake_db)

    monkeypatch.setenv("MBR_SYNC_TOKEN", "good-secret-xyz")

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_completed_without_token_is_rejected(client):
    r = client.get("/api/completed")
    assert r.status_code == 401


def test_completed_with_wrong_token_is_rejected(client):
    r = client.get("/api/completed", headers={"X-Sync-Token": "nope"})
    assert r.status_code == 401


def test_completed_with_correct_token_is_allowed(client):
    r = client.get("/api/completed", headers={"X-Sync-Token": "good-secret-xyz"})
    assert r.status_code == 200


def test_db_snapshot_without_token_is_rejected(client):
    r = client.get("/api/admin/db-snapshot")
    assert r.status_code == 401


def test_db_snapshot_with_correct_token_is_allowed(client):
    r = client.get("/api/admin/db-snapshot", headers={"X-Sync-Token": "good-secret-xyz"})
    assert r.status_code == 200


def test_sync_disabled_when_token_env_missing(monkeypatch, db, tmp_path):
    """If MBR_SYNC_TOKEN is unset/empty, both endpoints return 503 — fail closed."""
    import mbr.db
    import mbr.admin.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.routes, "db_session", fake_db_session)
    fake_db = tmp_path / "fake.sqlite"
    fake_db.write_bytes(b"SQLite fake")
    monkeypatch.setattr(mbr.db, "DB_PATH", fake_db)
    monkeypatch.delenv("MBR_SYNC_TOKEN", raising=False)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()

    r = c.get("/api/completed", headers={"X-Sync-Token": "anything"})
    assert r.status_code == 503
    r = c.get("/api/admin/db-snapshot", headers={"X-Sync-Token": "anything"})
    assert r.status_code == 503
