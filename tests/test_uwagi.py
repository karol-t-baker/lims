"""Tests for uwagi_koncowe (final batch notes) feature."""

import sqlite3
from datetime import datetime

import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    try:
        conn.execute("ALTER TABLE ebr_batches ADD COLUMN nr_zbiornika TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass
    yield conn
    conn.close()


@pytest.fixture
def ebr_batch(db):
    """Creates a minimal MBR template + open EBR batch, returns ebr_id."""
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
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, typ) "
        "VALUES (?, ?, ?, ?, 'open', 'szarza')",
        (mbr_id, "TestProduct__1", "1/2026", now),
    )
    db.commit()
    return db.execute(
        "SELECT ebr_id FROM ebr_batches WHERE batch_id='TestProduct__1'"
    ).fetchone()["ebr_id"]


def test_schema_has_uwagi_koncowe_column(db):
    """Regression test: ebr_batches must have uwagi_koncowe column after init."""
    cols = [r["name"] for r in db.execute("PRAGMA table_info(ebr_batches)").fetchall()]
    assert "uwagi_koncowe" in cols


def test_schema_has_history_table(db):
    """Regression test: ebr_uwagi_history table must exist."""
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ebr_uwagi_history'"
    ).fetchall()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Task 3: get_uwagi — empty state
# ---------------------------------------------------------------------------

from mbr.laborant.models import get_uwagi, save_uwagi


def test_get_uwagi_empty_for_new_batch(db, ebr_batch):
    result = get_uwagi(db, ebr_batch)
    assert result == {
        "tekst": None,
        "dt": None,
        "autor": None,
        "historia": [],
    }


# ---------------------------------------------------------------------------
# Task 4: save_uwagi — create
# ---------------------------------------------------------------------------

def test_save_uwagi_create(db, ebr_batch):
    save_uwagi(db, ebr_batch, "Dodano 500 kg NaOH", "kowalski")
    row = db.execute(
        "SELECT uwagi_koncowe FROM ebr_batches WHERE ebr_id = ?", (ebr_batch,)
    ).fetchone()
    assert row["uwagi_koncowe"] == "Dodano 500 kg NaOH"
    hist = db.execute(
        "SELECT tekst, action, autor FROM ebr_uwagi_history WHERE ebr_id = ?",
        (ebr_batch,),
    ).fetchall()
    assert len(hist) == 1
    assert hist[0]["tekst"] is None
    assert hist[0]["action"] == "create"
    assert hist[0]["autor"] == "kowalski"


# ---------------------------------------------------------------------------
# Task 5: save_uwagi — update
# ---------------------------------------------------------------------------

def test_save_uwagi_update_stores_old_text(db, ebr_batch):
    save_uwagi(db, ebr_batch, "wersja A", "kowalski")
    save_uwagi(db, ebr_batch, "wersja B", "nowak")
    row = db.execute(
        "SELECT uwagi_koncowe FROM ebr_batches WHERE ebr_id = ?", (ebr_batch,)
    ).fetchone()
    assert row["uwagi_koncowe"] == "wersja B"
    hist = db.execute(
        "SELECT tekst, action, autor FROM ebr_uwagi_history "
        "WHERE ebr_id = ? ORDER BY id",
        (ebr_batch,),
    ).fetchall()
    assert len(hist) == 2
    assert hist[0]["action"] == "create"
    assert hist[0]["tekst"] is None
    assert hist[1]["action"] == "update"
    assert hist[1]["tekst"] == "wersja A"
    assert hist[1]["autor"] == "nowak"


# ---------------------------------------------------------------------------
# Task 6: save_uwagi — delete + noop + whitespace
# ---------------------------------------------------------------------------

def test_save_uwagi_delete(db, ebr_batch):
    save_uwagi(db, ebr_batch, "do skasowania", "kowalski")
    save_uwagi(db, ebr_batch, "", "nowak")
    row = db.execute(
        "SELECT uwagi_koncowe FROM ebr_batches WHERE ebr_id = ?", (ebr_batch,)
    ).fetchone()
    assert row["uwagi_koncowe"] is None
    hist = db.execute(
        "SELECT tekst, action FROM ebr_uwagi_history "
        "WHERE ebr_id = ? ORDER BY id",
        (ebr_batch,),
    ).fetchall()
    assert len(hist) == 2
    assert hist[1]["action"] == "delete"
    assert hist[1]["tekst"] == "do skasowania"


def test_save_uwagi_noop_on_null_to_empty(db, ebr_batch):
    save_uwagi(db, ebr_batch, "   ", "kowalski")
    row = db.execute(
        "SELECT uwagi_koncowe FROM ebr_batches WHERE ebr_id = ?", (ebr_batch,)
    ).fetchone()
    assert row["uwagi_koncowe"] is None
    hist = db.execute(
        "SELECT * FROM ebr_uwagi_history WHERE ebr_id = ?", (ebr_batch,)
    ).fetchall()
    assert len(hist) == 0


def test_save_uwagi_noop_on_same_text(db, ebr_batch):
    save_uwagi(db, ebr_batch, "ten sam", "kowalski")
    save_uwagi(db, ebr_batch, "ten sam", "nowak")
    hist = db.execute(
        "SELECT COUNT(*) as c FROM ebr_uwagi_history WHERE ebr_id = ?",
        (ebr_batch,),
    ).fetchone()
    assert hist["c"] == 1


def test_save_uwagi_strips_whitespace(db, ebr_batch):
    save_uwagi(db, ebr_batch, "  z białymi znakami  ", "kowalski")
    row = db.execute(
        "SELECT uwagi_koncowe FROM ebr_batches WHERE ebr_id = ?", (ebr_batch,)
    ).fetchone()
    assert row["uwagi_koncowe"] == "z białymi znakami"


# ---------------------------------------------------------------------------
# Task 7: validation errors
# ---------------------------------------------------------------------------

def test_save_uwagi_rejects_too_long(db, ebr_batch):
    with pytest.raises(ValueError, match="500"):
        save_uwagi(db, ebr_batch, "a" * 501, "kowalski")


def test_save_uwagi_allows_exactly_500(db, ebr_batch):
    text = "a" * 500
    save_uwagi(db, ebr_batch, text, "kowalski")
    row = db.execute(
        "SELECT uwagi_koncowe FROM ebr_batches WHERE ebr_id = ?", (ebr_batch,)
    ).fetchone()
    assert row["uwagi_koncowe"] == text


def test_save_uwagi_rejects_cancelled_batch(db, ebr_batch):
    db.execute(
        "UPDATE ebr_batches SET status='cancelled' WHERE ebr_id = ?",
        (ebr_batch,),
    )
    db.commit()
    with pytest.raises(ValueError, match="anulowanej"):
        save_uwagi(db, ebr_batch, "anything", "kowalski")


def test_save_uwagi_rejects_missing_batch(db):
    with pytest.raises(ValueError, match="not found"):
        save_uwagi(db, 9999, "anything", "kowalski")


# ---------------------------------------------------------------------------
# Task 8: get_uwagi — populated state + after-delete
# ---------------------------------------------------------------------------

def test_get_uwagi_returns_current_meta_from_history(db, ebr_batch):
    save_uwagi(db, ebr_batch, "pierwsza", "kowalski")
    save_uwagi(db, ebr_batch, "druga", "nowak")
    result = get_uwagi(db, ebr_batch)
    assert result["tekst"] == "druga"
    assert result["autor"] == "nowak"
    assert result["dt"] is not None
    assert len(result["historia"]) == 2
    assert result["historia"][0]["action"] == "update"
    assert result["historia"][1]["action"] == "create"


def test_get_uwagi_after_delete(db, ebr_batch):
    save_uwagi(db, ebr_batch, "temporary", "kowalski")
    save_uwagi(db, ebr_batch, "", "nowak")
    result = get_uwagi(db, ebr_batch)
    assert result["tekst"] is None
    assert result["autor"] is None
    assert len(result["historia"]) == 2
    assert result["historia"][0]["action"] == "delete"


# ---------------------------------------------------------------------------
# Tasks 9-11: Flask HTTP API tests
# ---------------------------------------------------------------------------

def _make_client(monkeypatch, db, rola="laborant", shift_workers=None):
    """Build a Flask test client whose db_session yields the given in-memory db."""
    from contextlib import contextmanager
    import mbr.db
    import mbr.laborant.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"login": "testuser", "rola": rola}
            if shift_workers is not None:
                sess["shift_workers"] = shift_workers
        yield c


@pytest.fixture
def client(monkeypatch, db, ebr_batch):
    # Seed a worker whose nickname matches the session login, and put them
    # into shift_workers so Phase 3 enforcement (laborant must have a shift)
    # is satisfied while keeping legacy autor == "testuser" assertions valid.
    db.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (999, 'Test', 'User', 'TU', 'testuser', 1)"
    )
    db.commit()
    yield from _make_client(monkeypatch, db, rola="laborant", shift_workers=[999])


@pytest.fixture
def client_technolog(monkeypatch, db, ebr_batch):
    yield from _make_client(monkeypatch, db, rola="technolog")


# GET tests

def test_api_get_uwagi_empty(client, ebr_batch):
    resp = client.get(f"/api/ebr/{ebr_batch}/uwagi")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"tekst": None, "dt": None, "autor": None, "historia": []}


def test_api_get_accessible_to_technolog(client_technolog, ebr_batch):
    resp = client_technolog.get(f"/api/ebr/{ebr_batch}/uwagi")
    assert resp.status_code == 200


# PUT tests

def test_api_put_uwagi_create(client, ebr_batch):
    resp = client.put(
        f"/api/ebr/{ebr_batch}/uwagi",
        json={"tekst": "Dodano 500 kg NaOH"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["tekst"] == "Dodano 500 kg NaOH"
    assert data["autor"] == "testuser"
    assert len(data["historia"]) == 1
    assert data["historia"][0]["action"] == "create"


def test_api_put_uwagi_too_long(client, ebr_batch):
    resp = client.put(
        f"/api/ebr/{ebr_batch}/uwagi",
        json={"tekst": "a" * 501},
    )
    assert resp.status_code == 400
    assert "500" in resp.get_json()["error"]


def test_api_put_uwagi_cancelled_batch(client, db, ebr_batch):
    db.execute(
        "UPDATE ebr_batches SET status='cancelled' WHERE ebr_id = ?",
        (ebr_batch,),
    )
    db.commit()
    resp = client.put(
        f"/api/ebr/{ebr_batch}/uwagi",
        json={"tekst": "anything"},
    )
    assert resp.status_code == 400
    assert "anulowanej" in resp.get_json()["error"]


def test_api_put_uwagi_missing_batch(client):
    resp = client.put(
        "/api/ebr/99999/uwagi",
        json={"tekst": "whatever"},
    )
    assert resp.status_code == 404


def test_api_put_forbidden_for_technolog(client_technolog, ebr_batch):
    resp = client_technolog.put(
        f"/api/ebr/{ebr_batch}/uwagi",
        json={"tekst": "nope"},
    )
    assert resp.status_code in (403, 302)


# DELETE tests

def test_api_delete_uwagi(client, ebr_batch):
    client.put(f"/api/ebr/{ebr_batch}/uwagi", json={"tekst": "to delete"})
    resp = client.delete(f"/api/ebr/{ebr_batch}/uwagi")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["tekst"] is None
    assert len(data["historia"]) == 2


def test_api_delete_uwagi_noop(client, ebr_batch):
    resp = client.delete(f"/api/ebr/{ebr_batch}/uwagi")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["tekst"] is None
    assert data["historia"] == []


# ---------------------------------------------------------------------------
# _resolve_actor_label — helper that picks the autor string for write routes
# ---------------------------------------------------------------------------

def _seed_workers(db):
    db.execute("INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname) VALUES (1, 'Anna', 'Kowalska', 'AK', 'AK')")
    db.execute("INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname) VALUES (2, 'Maria', 'Wojcik', 'MW', 'MW')")
    db.commit()


def test_resolve_actor_label_falls_back_to_login_for_non_laborant_roles(db):
    """Empty shift_workers → autor = session login for admin/technolog/laborant_kj/laborant_coa.
    For role 'laborant', see test_resolve_actor_label_laborant_empty_shift_raises."""
    from flask import Flask
    from mbr.laborant.routes import _resolve_actor_label
    app = Flask(__name__)
    app.secret_key = "test"
    for rola in ("admin", "technolog", "laborant_kj", "laborant_coa"):
        with app.test_request_context():
            from flask import session
            session["user"] = {"login": "shared_lab", "rola": rola}
            assert _resolve_actor_label(db) == "shared_lab"


def test_resolve_actor_label_laborant_empty_shift_raises(db):
    """Empty shift_workers + role='laborant' → ShiftRequiredError (Phase 3 enforcement)."""
    from flask import Flask
    from mbr.laborant.routes import _resolve_actor_label
    from mbr.shared.audit import ShiftRequiredError
    import pytest as _pytest
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        from flask import session
        session["user"] = {"login": "shared_lab", "rola": "laborant"}
        with _pytest.raises(ShiftRequiredError):
            _resolve_actor_label(db)


def test_resolve_actor_label_uses_shift_when_set(db):
    """Non-empty shift_workers → joined nicknames."""
    _seed_workers(db)
    from flask import Flask
    from mbr.laborant.routes import _resolve_actor_label
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        from flask import session
        session["user"] = {"login": "shared_lab", "rola": "laborant"}
        session["shift_workers"] = [1, 2]
        assert _resolve_actor_label(db) == "AK, MW"


def test_resolve_actor_label_override_wins(db):
    """Explicit override (e.g. from picker) takes precedence over shift."""
    _seed_workers(db)
    from flask import Flask
    from mbr.laborant.routes import _resolve_actor_label
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        from flask import session
        session["user"] = {"login": "shared_lab", "rola": "laborant"}
        session["shift_workers"] = [1, 2]
        assert _resolve_actor_label(db, override="AK") == "AK"


def test_resolve_actor_label_empty_string_override_ignored(db):
    """Override of '' or whitespace is ignored — falls through to shift."""
    _seed_workers(db)
    from flask import Flask
    from mbr.laborant.routes import _resolve_actor_label
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        from flask import session
        session["user"] = {"login": "shared_lab", "rola": "laborant"}
        session["shift_workers"] = [1]
        assert _resolve_actor_label(db, override="") == "AK"
        assert _resolve_actor_label(db, override="   ") == "AK"


def test_resolve_actor_label_nickname_falls_through_to_inicjaly(db):
    """Worker with empty nickname uses inicjaly instead."""
    db.execute("INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname) VALUES (3, 'Jan', 'Nowak', 'JN', '')")
    db.commit()
    from flask import Flask
    from mbr.laborant.routes import _resolve_actor_label
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        from flask import session
        session["user"] = {"login": "x", "rola": "laborant"}
        session["shift_workers"] = [3]
        assert _resolve_actor_label(db) == "JN"


# ---------------------------------------------------------------------------
# uwagi PUT — autor override via body (UI picker)
# ---------------------------------------------------------------------------

def test_api_put_uwagi_uses_shift_when_no_override(monkeypatch, db, ebr_batch):
    """When body lacks 'autor', the route resolves it from shift_workers."""
    _seed_workers(db)

    from contextlib import contextmanager
    import mbr.db, mbr.laborant.routes
    @contextmanager
    def fake_db_session():
        yield db
    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"login": "shared_lab", "rola": "laborant"}
            sess["shift_workers"] = [1, 2]
        resp = c.put(f"/api/ebr/{ebr_batch}/uwagi", json={"tekst": "Praca pary"})
        assert resp.status_code == 200
        assert resp.get_json()["autor"] == "AK, MW"


def test_api_put_uwagi_explicit_autor_overrides_shift(monkeypatch, db, ebr_batch):
    """When body provides 'autor', it wins over shift workers."""
    _seed_workers(db)

    from contextlib import contextmanager
    import mbr.db, mbr.laborant.routes
    @contextmanager
    def fake_db_session():
        yield db
    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"login": "shared_lab", "rola": "laborant"}
            sess["shift_workers"] = [1, 2]
        resp = c.put(
            f"/api/ebr/{ebr_batch}/uwagi",
            json={"tekst": "Tylko ja", "autor": "AK"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["autor"] == "AK"
