"""Tests for GET/PUT /api/cert/settings — global cert typography settings API."""
import sqlite3
import pytest
from pathlib import Path
from mbr.app import create_app
from mbr.models import init_mbr_tables


@pytest.fixture
def app_ctx(tmp_path, monkeypatch):
    db_file = tmp_path / "test.sqlite"
    import mbr.db as db_module
    monkeypatch.setattr(db_module, "_DB_PATH", str(db_file), raising=False)
    if hasattr(db_module, "DB_PATH"):
        monkeypatch.setattr(db_module, "DB_PATH", str(db_file), raising=False)
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    conn.close()
    app = create_app()
    app.config["TESTING"] = True
    return app, db_file


@pytest.fixture
def client(app_ctx):
    app, _ = app_ctx
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = {"login": "admin", "rola": "admin", "id": 1}
    return c


@pytest.fixture
def db_path(app_ctx):
    _, db_file = app_ctx
    return db_file


def test_cert_settings_get_returns_defaults(client):
    r = client.get("/api/cert/settings")
    assert r.status_code == 200
    data = r.get_json()
    assert data["body_font_family"] == "Bookman Old Style"
    assert data["header_font_size_pt"] == 14


def test_cert_settings_put_updates_both_keys(client, db_path):
    r = client.put("/api/cert/settings", json={
        "body_font_family": "EB Garamond",
        "header_font_size_pt": 18,
    })
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}
    # Verify GET reflects the change
    r2 = client.get("/api/cert/settings")
    data = r2.get_json()
    assert data["body_font_family"] == "EB Garamond"
    assert data["header_font_size_pt"] == 18


def test_cert_settings_put_writes_audit_event(client, db_path):
    client.put("/api/cert/settings", json={"body_font_family": "Bitter", "header_font_size_pt": 16})
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT event_type, payload_json FROM audit_log WHERE event_type=? ORDER BY dt DESC LIMIT 1",
        ("cert.settings.updated",),
    ).fetchone()
    conn.close()
    assert row is not None
    assert "Bitter" in row[1] or "16" in row[1]


def test_cert_settings_put_rejects_header_size_out_of_range(client):
    r = client.put("/api/cert/settings", json={"header_font_size_pt": 500})
    assert r.status_code == 400
    data = r.get_json()
    assert "error" in data


def test_cert_settings_put_rejects_header_size_negative(client):
    r = client.put("/api/cert/settings", json={"header_font_size_pt": -5})
    assert r.status_code == 400


def test_cert_settings_put_rejects_empty_font(client):
    r = client.put("/api/cert/settings", json={"body_font_family": "   "})
    assert r.status_code == 400


def test_cert_settings_put_partial_update(client):
    # Only update font, not size
    r = client.put("/api/cert/settings", json={"body_font_family": "Merriweather"})
    assert r.status_code == 200
    r2 = client.get("/api/cert/settings")
    data = r2.get_json()
    assert data["body_font_family"] == "Merriweather"
    # Default still applies to size
    assert data["header_font_size_pt"] == 14


def test_cert_settings_put_empty_body_400(client):
    r = client.put("/api/cert/settings", json={})
    assert r.status_code == 400


def test_cert_settings_put_rejects_xml_unsafe_font(client):
    """Font name with XML-special chars (quotes, angle brackets, ampersand) must be rejected."""
    r = client.put("/api/cert/settings", json={"body_font_family": 'Bad" font'})
    assert r.status_code == 400
    r2 = client.put("/api/cert/settings", json={"body_font_family": "Bad<font>"})
    assert r2.status_code == 400
    r3 = client.put("/api/cert/settings", json={"body_font_family": "Bad&font"})
    assert r3.status_code == 400
