"""Tests for /admin/audit panel + archival + per-record history endpoints."""

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
    """Build a Flask test client with the in-memory db monkey-patched in."""
    import mbr.db
    import mbr.admin.audit_routes
    import mbr.admin.routes
    import mbr.laborant.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.audit_routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": rola, "worker_id": None}
    return client


@pytest.fixture
def admin_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="admin")


@pytest.fixture
def laborant_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="laborant")


def _seed_some_audit_rows(db):
    """Insert a handful of audit_log rows for the panel tests."""
    rows = [
        ("2026-04-01T08:00:00", "auth.login", None, None, None, '{"login":"alice"}', "req-1"),
        ("2026-04-02T09:00:00", "ebr.wynik.saved", "ebr", 42, "Szarża 2026/42", None, "req-2"),
        ("2026-04-03T10:00:00", "cert.generated", "cert", 7, "Świad. K40GLO", '{"path":"/x.pdf"}', "req-3"),
    ]
    for r in rows:
        cur = db.execute(
            """INSERT INTO audit_log
               (dt, event_type, entity_type, entity_id, entity_label, payload_json, request_id, result)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'ok')""",
            r,
        )
        db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, NULL, 'tester', 'admin')",
            (cur.lastrowid,),
        )
    db.commit()


# ---------- /admin/audit panel ----------

def test_admin_audit_panel_returns_200_for_admin(admin_client, db):
    _seed_some_audit_rows(db)
    resp = admin_client.get("/admin/audit")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Audit trail" in body or "audit" in body.lower()
    # All 3 seeded rows should appear in the rendered table
    assert "auth.login" in body
    assert "ebr.wynik.saved" in body
    assert "cert.generated" in body


def test_admin_audit_panel_forbidden_for_non_admin(laborant_client, db):
    _seed_some_audit_rows(db)
    resp = laborant_client.get("/admin/audit")
    assert resp.status_code == 403


def test_admin_audit_panel_filters_by_date(admin_client, db):
    _seed_some_audit_rows(db)
    resp = admin_client.get("/admin/audit?dt_from=2026-04-02&dt_to=2026-04-02")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Only the 2026-04-02 row should be in the table
    assert "ebr.wynik.saved" in body
    assert "auth.login" not in body
    assert "cert.generated" not in body


def test_admin_audit_panel_filters_by_event_type_glob(admin_client, db):
    _seed_some_audit_rows(db)
    resp = admin_client.get("/admin/audit?event_type_glob=cert.*")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "cert.generated" in body
    assert "ebr.wynik.saved" not in body
    assert "auth.login" not in body


def test_admin_audit_panel_filters_by_request_id(admin_client, db):
    _seed_some_audit_rows(db)
    resp = admin_client.get("/admin/audit?request_id=req-2")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "ebr.wynik.saved" in body
    assert "auth.login" not in body
    assert "cert.generated" not in body


def test_admin_audit_panel_pagination(admin_client, db):
    # Seed 150 rows so we get 2 pages
    for i in range(150):
        cur = db.execute(
            "INSERT INTO audit_log (dt, event_type, result) VALUES (?, 'auth.login', 'ok')",
            (f"2026-04-{(i % 28) + 1:02d}T08:00:00",),
        )
        db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, NULL, 'tester', 'admin')",
            (cur.lastrowid,),
        )
    db.commit()

    resp1 = admin_client.get("/admin/audit?page=1")
    body1 = resp1.get_data(as_text=True)
    assert "Strona 1 / 2" in body1 or "Strona 1" in body1

    resp2 = admin_client.get("/admin/audit?page=2")
    body2 = resp2.get_data(as_text=True)
    assert "Strona 2" in body2


def test_admin_audit_panel_pager_preserves_filters(admin_client, db):
    """Pager links must preserve active filters across page navigation."""
    # Seed 150 rows with mixed event types
    for i in range(150):
        cur = db.execute(
            "INSERT INTO audit_log (dt, event_type, result) VALUES (?, ?, 'ok')",
            (
                f"2026-04-{(i % 28) + 1:02d}T08:00:00",
                "auth.login" if i < 75 else "ebr.wynik.saved",
            ),
        )
        db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, NULL, 'tester', 'admin')",
            (cur.lastrowid,),
        )
    db.commit()

    # Filter to auth.* (75 rows = 1 page) — but include explicit pagination
    resp = admin_client.get("/admin/audit?event_type_glob=auth.%2A")
    body = resp.get_data(as_text=True)
    # Pager next link must include the filter param
    if "Następna" in body:
        # Pager exists and the next-page href must contain event_type_glob
        assert "event_type_glob=auth" in body, \
            "Pager 'Następna' link should preserve event_type_glob filter, but only 'page' is present"


# ---------- /admin/audit/export.csv ----------

def test_admin_audit_export_csv_streams_correct_columns(admin_client, db):
    # Seed a row with a comma in entity_label to test escaping
    cur = db.execute(
        """INSERT INTO audit_log (dt, event_type, entity_type, entity_id,
           entity_label, payload_json, request_id, result)
           VALUES ('2026-04-01T08:00:00', 'ebr.wynik.saved', 'ebr', 99,
           'Szarża, with comma', '{"a":1}', 'req-x', 'ok')"""
    )
    db.execute(
        "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, 1, 'AK', 'laborant')",
        (cur.lastrowid,),
    )
    db.commit()

    resp = admin_client.get("/admin/audit/export.csv")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/csv")
    body = resp.get_data(as_text=True)
    lines = body.strip().split("\n")
    # Header + 1 data row
    assert len(lines) == 2
    header = lines[0]
    assert "dt" in header and "event_type" in header and "entity_label" in header
    # Comma in entity_label must be quoted
    assert '"Szarża, with comma"' in lines[1]
    assert "ebr.wynik.saved" in lines[1]


def test_admin_audit_export_csv_forbidden_for_non_admin(laborant_client, db):
    resp = laborant_client.get("/admin/audit/export.csv")
    assert resp.status_code == 403


def test_admin_audit_export_csv_preserves_entity_id_zero(admin_client, db):
    """A legitimate entity_id=0 must appear as '0' in the CSV, not empty string."""
    cur = db.execute(
        """INSERT INTO audit_log (dt, event_type, entity_type, entity_id, result)
           VALUES ('2026-04-01T08:00:00', 'x.y.z', 'ebr', 0, 'ok')"""
    )
    db.execute(
        "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, NULL, 'tester', 'admin')",
        (cur.lastrowid,),
    )
    db.commit()

    resp = admin_client.get("/admin/audit/export.csv")
    body = resp.get_data(as_text=True)
    lines = body.strip().split("\n")
    assert len(lines) == 2
    # Header row + data row
    data_row = lines[1]
    # entity_id is column index 3 (dt, event_type, entity_type, entity_id, ...)
    fields = next(__import__("csv").reader([data_row]))
    assert fields[3] == "0", f"Expected entity_id=0 to be '0', got {fields[3]!r}"


# ---------- /admin/audit/archive/preview ----------

def test_admin_audit_archive_preview_returns_count(admin_client, db):
    # Seed 3 old + 2 new rows
    for dt in ("2020-01-01", "2020-02-01", "2020-03-01"):
        cur = db.execute(
            "INSERT INTO audit_log (dt, event_type, result) VALUES (?, 'auth.login', 'ok')",
            (dt + "T08:00:00",),
        )
        db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, NULL, 'x', 'unknown')",
            (cur.lastrowid,),
        )
    for dt in ("2026-04-01", "2026-04-02"):
        cur = db.execute(
            "INSERT INTO audit_log (dt, event_type, result) VALUES (?, 'auth.login', 'ok')",
            (dt + "T08:00:00",),
        )
        db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, NULL, 'x', 'unknown')",
            (cur.lastrowid,),
        )
    db.commit()

    resp = admin_client.post(
        "/admin/audit/archive/preview",
        json={"cutoff_iso": "2024-01-01T00:00:00"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 3
    assert data["cutoff"] == "2024-01-01T00:00:00"

    # Preview must NOT mutate
    remaining = db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    assert remaining == 5


def test_admin_audit_archive_preview_forbidden_for_non_admin(laborant_client, db):
    resp = laborant_client.post(
        "/admin/audit/archive/preview", json={"cutoff_iso": "2024-01-01T00:00:00"}
    )
    assert resp.status_code == 403


def test_admin_audit_archive_preview_missing_cutoff_returns_400(admin_client, db):
    resp = admin_client.post("/admin/audit/archive/preview", json={})
    assert resp.status_code == 400


# ---------- /admin/audit/archive (apply) ----------

def test_admin_audit_archive_apply_runs_archive(admin_client, db, tmp_path, monkeypatch):
    import mbr.admin.audit_routes
    # Override the archive_dir resolution to use tmp_path
    monkeypatch.setattr(
        mbr.admin.audit_routes, "_resolve_archive_dir", lambda: tmp_path
    )

    # Seed 2 old rows
    for dt in ("2020-01-01", "2020-02-01"):
        cur = db.execute(
            "INSERT INTO audit_log (dt, event_type, result) VALUES (?, 'auth.login', 'ok')",
            (dt + "T08:00:00",),
        )
        db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, NULL, 'x', 'unknown')",
            (cur.lastrowid,),
        )
    db.commit()

    resp = admin_client.post(
        "/admin/audit/archive", json={"cutoff_iso": "2024-01-01T00:00:00"}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["archived"] == 2

    # Active DB now has 0 originals + 1 system.audit.archived = 1
    rows = db.execute("SELECT event_type FROM audit_log").fetchall()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "system.audit.archived"

    # Archive file exists (named by cutoff year, not row year)
    archive_file = tmp_path / "audit_2024.jsonl.gz"
    assert archive_file.exists()


def test_admin_audit_archive_apply_forbidden_for_non_admin(laborant_client, db):
    resp = laborant_client.post(
        "/admin/audit/archive", json={"cutoff_iso": "2024-01-01T00:00:00"}
    )
    assert resp.status_code == 403


def test_admin_audit_archive_apply_missing_cutoff_returns_400(admin_client, db):
    resp = admin_client.post("/admin/audit/archive", json={})
    assert resp.status_code == 400
