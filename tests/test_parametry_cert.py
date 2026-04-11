"""Tests for parametry_cert table and parametry_analityczne extensions."""

import sqlite3
import pytest
from flask import Flask
from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


@pytest.fixture
def app(db):
    from mbr.parametry import parametry_bp
    _app = Flask(__name__)
    _app.secret_key = "test"

    import mbr.parametry.routes as _routes
    _orig = _routes.db_session

    from contextlib import contextmanager

    @contextmanager
    def _test_db_session():
        yield db

    _routes.db_session = _test_db_session
    _app.register_blueprint(parametry_bp)

    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, precision) "
        "VALUES ('sm', 'Sucha masa', 'bezposredni', 1)"
    )
    db.commit()

    yield _app
    _routes.db_session = _orig


@pytest.fixture
def client(app):
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"login": "admin", "rola": "admin"}
        yield c


def test_parametry_analityczne_has_name_en(db):
    """INSERT with name_en and method_code, verify they're readable."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, name_en, method_code) "
        "VALUES ('ph', 'pH', 'bezposredni', 'pH value', 'L928')"
    )
    db.commit()
    row = db.execute(
        "SELECT name_en, method_code FROM parametry_analityczne WHERE kod = 'ph'"
    ).fetchone()
    assert row is not None
    assert row["name_en"] == "pH value"
    assert row["method_code"] == "L928"


def test_parametry_cert_table_exists(db):
    """INSERT into parametry_cert, verify fields."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ) VALUES ('ph', 'pH', 'bezposredni')"
    )
    db.commit()
    param_id = db.execute(
        "SELECT id FROM parametry_analityczne WHERE kod = 'ph'"
    ).fetchone()["id"]

    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, qualitative_result) "
        "VALUES ('K40GLO', ?, 1, '6.5-7.5', '2', NULL)",
        (param_id,),
    )
    db.commit()
    row = db.execute(
        "SELECT produkt, parametr_id, kolejnosc, requirement, format, qualitative_result "
        "FROM parametry_cert WHERE produkt = 'K40GLO'"
    ).fetchone()
    assert row is not None
    assert row["produkt"] == "K40GLO"
    assert row["parametr_id"] == param_id
    assert row["kolejnosc"] == 1
    assert row["requirement"] == "6.5-7.5"
    assert row["format"] == "2"
    assert row["qualitative_result"] is None


def test_parametry_cert_unique_constraint(db):
    """Verify UNIQUE(produkt, parametr_id) constraint."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ) VALUES ('ph', 'pH', 'bezposredni')"
    )
    db.commit()
    param_id = db.execute(
        "SELECT id FROM parametry_analityczne WHERE kod = 'ph'"
    ).fetchone()["id"]

    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id) VALUES ('K40GLO', ?)",
        (param_id,),
    )
    db.commit()

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO parametry_cert (produkt, parametr_id) VALUES ('K40GLO', ?)",
            (param_id,),
        )
        db.commit()


def test_seed_has_name_en(db):
    """Verify seed populates name_en for key parameters."""
    from mbr.parametry.seed import seed
    seed(db)
    row = db.execute("SELECT name_en, method_code FROM parametry_analityczne WHERE kod='sm'").fetchone()
    assert row["name_en"] == "Dry matter [%]"
    assert row["method_code"] == "L903"


def test_seed_has_name_en_ph(db):
    from mbr.parametry.seed import seed
    seed(db)
    row = db.execute("SELECT name_en FROM parametry_analityczne WHERE kod='ph_10proc'").fetchone()
    assert row["name_en"] == "pH (20°C)"


def test_jakosciowy_typ_allowed(db):
    """INSERT with typ='jakosciowy', verify it works."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ) VALUES ('wyglad', 'Wygląd', 'jakosciowy')"
    )
    db.commit()
    row = db.execute(
        "SELECT typ FROM parametry_analityczne WHERE kod = 'wyglad'"
    ).fetchone()
    assert row is not None
    assert row["typ"] == "jakosciowy"


# --- API endpoint tests ---


def _get_param_id(db):
    return db.execute(
        "SELECT id FROM parametry_analityczne WHERE kod='sm'"
    ).fetchone()["id"]


def test_get_cert_bindings_empty(client):
    """GET returns empty list for unknown product."""
    resp = client.get("/api/parametry/cert/UNKNOWN_PRODUCT")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_create_cert_binding(client, db):
    """POST creates binding, returns ok + id."""
    param_id = _get_param_id(db)
    resp = client.post(
        "/api/parametry/cert",
        json={"produkt": "K40GLO", "parametr_id": param_id, "kolejnosc": 1, "requirement": "min 40%"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert isinstance(data["id"], int)

    # Verify it's readable via GET
    resp2 = client.get("/api/parametry/cert/K40GLO")
    rows = resp2.get_json()
    assert len(rows) == 1
    assert rows[0]["requirement"] == "min 40%"
    assert rows[0]["kod"] == "sm"


def test_update_cert_binding(client, db):
    """PUT updates requirement field."""
    param_id = _get_param_id(db)
    create_resp = client.post(
        "/api/parametry/cert",
        json={"produkt": "K40GLO", "parametr_id": param_id, "kolejnosc": 1, "requirement": "old"},
    )
    binding_id = create_resp.get_json()["id"]

    resp = client.put(f"/api/parametry/cert/{binding_id}", json={"requirement": "new"})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    row = db.execute("SELECT requirement FROM parametry_cert WHERE id=?", (binding_id,)).fetchone()
    assert row["requirement"] == "new"


def test_delete_cert_binding(client, db):
    """DELETE removes binding."""
    param_id = _get_param_id(db)
    create_resp = client.post(
        "/api/parametry/cert",
        json={"produkt": "K40GLO", "parametr_id": param_id, "kolejnosc": 1},
    )
    binding_id = create_resp.get_json()["id"]

    resp = client.delete(f"/api/parametry/cert/{binding_id}")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    row = db.execute("SELECT id FROM parametry_cert WHERE id=?", (binding_id,)).fetchone()
    assert row is None


def test_reorder_cert_bindings(client, db):
    """POST reorder swaps kolejnosc for two bindings."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ) VALUES ('nd', 'Refraktometr', 'bezposredni')"
    )
    db.commit()
    param_id_sm = _get_param_id(db)
    param_id_nd = db.execute("SELECT id FROM parametry_analityczne WHERE kod='nd'").fetchone()["id"]

    r1 = client.post(
        "/api/parametry/cert",
        json={"produkt": "K40GLO", "parametr_id": param_id_sm, "kolejnosc": 1},
    ).get_json()["id"]
    r2 = client.post(
        "/api/parametry/cert",
        json={"produkt": "K40GLO", "parametr_id": param_id_nd, "kolejnosc": 2},
    ).get_json()["id"]

    resp = client.post(
        "/api/parametry/cert/reorder",
        json={"bindings": [{"id": r1, "kolejnosc": 2}, {"id": r2, "kolejnosc": 1}]},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    row1 = db.execute("SELECT kolejnosc FROM parametry_cert WHERE id=?", (r1,)).fetchone()
    row2 = db.execute("SELECT kolejnosc FROM parametry_cert WHERE id=?", (r2,)).fetchone()
    assert row1["kolejnosc"] == 2
    assert row2["kolejnosc"] == 1
