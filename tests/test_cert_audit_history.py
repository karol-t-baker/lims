"""Tests for GET /api/cert/config/product/<key>/audit-history."""
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


def _log_cert_event(db_path, entity_label, payload):
    """Insert a cert.config.updated audit event directly."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    from mbr.shared import audit
    audit.log_event(
        audit.EVENT_CERT_CONFIG_UPDATED,
        entity_type="cert",
        entity_label=entity_label,
        payload=payload,
        actors=[{"worker_id": None, "actor_login": "admin", "actor_rola": "admin", "actor_name": "admin"}],
        db=conn,
    )
    conn.commit()
    conn.close()


def test_audit_history_per_product_filters_by_label(client, db_path):
    _log_cert_event(db_path, "PROD_A", {"params_count": 1, "variants_count": 1})
    _log_cert_event(db_path, "PROD_B", {"params_count": 5, "variants_count": 1})
    _log_cert_event(db_path, "PROD_A", {"params_count": 2, "variants_count": 2})

    r = client.get("/api/cert/config/product/PROD_A/audit-history")
    assert r.status_code == 200
    data = r.get_json()
    assert "history" in data
    # Two PROD_A events, zero PROD_B
    assert len(data["history"]) == 2
    for row in data["history"]:
        assert row["entity_label"] == "PROD_A"


def test_audit_history_empty_for_unknown_product(client):
    r = client.get("/api/cert/config/product/DOESNOTEXIST/audit-history")
    assert r.status_code == 200
    data = r.get_json()
    assert data["history"] == []


def test_audit_history_sorted_desc(client, db_path):
    _log_cert_event(db_path, "SORT_TEST", {"params_count": 1, "variants_count": 1})
    import time
    time.sleep(1.0)  # guarantee distinct dt values
    _log_cert_event(db_path, "SORT_TEST", {"params_count": 2, "variants_count": 2})

    r = client.get("/api/cert/config/product/SORT_TEST/audit-history")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data["history"]) == 2
    # Newest first
    assert data["history"][0]["dt"] > data["history"][1]["dt"]
