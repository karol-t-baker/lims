import sqlite3
import pytest
from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def test_new_pipeline_tables_exist(db):
    tables = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    for t in [
        "etapy_analityczne", "etap_parametry", "produkt_pipeline",
        "produkt_etap_limity", "etap_warunki", "etap_korekty_katalog",
        "ebr_etap_sesja", "ebr_pomiar", "ebr_korekta_v2",
    ]:
        assert t in tables, f"Missing table: {t}"


def test_etapy_analityczne_columns(db):
    cols = [r[1] for r in db.execute("PRAGMA table_info(etapy_analityczne)").fetchall()]
    assert "kod" in cols
    assert "typ_cyklu" in cols
    assert "aktywny" in cols


def test_etapy_analityczne_unique_kod(db):
    db.execute("INSERT INTO etapy_analityczne (kod, nazwa) VALUES ('test', 'Test')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO etapy_analityczne (kod, nazwa) VALUES ('test', 'Test2')")


def test_etap_parametry_fk(db):
    db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa) VALUES (1, 'amid', 'Amid')")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (9999, 'ph_test', 'pH', 'bezposredni')")
    db.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (1, 9999, 1)")
    row = db.execute("SELECT * FROM etap_parametry WHERE etap_id=1").fetchone()
    assert row is not None


def test_ebr_etap_sesja_unique_constraint(db):
    db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa) VALUES (1, 'amid', 'Amid')")
    db.execute("""INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia)
                  VALUES (1, 'Test', 1, '2026-01-01')""")
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start)
                  VALUES (1, 1, 'T-1', '1/2026', '2026-01-01')""")
    db.execute("""INSERT INTO ebr_etap_sesja (ebr_id, etap_id, runda) VALUES (1, 1, 1)""")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("""INSERT INTO ebr_etap_sesja (ebr_id, etap_id, runda) VALUES (1, 1, 1)""")


def test_ebr_pomiar_unique_constraint(db):
    db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa) VALUES (1, 'amid', 'Amid')")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (9999, 'ph_test', 'pH', 'bezposredni')")
    db.execute("""INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia)
                  VALUES (1, 'Test', 1, '2026-01-01')""")
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start)
                  VALUES (1, 1, 'T-1', '1/2026', '2026-01-01')""")
    db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda) VALUES (1, 1, 1, 1)")
    db.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, dt_wpisu, wpisal) VALUES (1, 9999, 7.5, '2026-01-01', 'lab1')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, dt_wpisu, wpisal) VALUES (1, 9999, 7.6, '2026-01-01', 'lab1')")
