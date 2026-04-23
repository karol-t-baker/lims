import sqlite3
import pytest

from mbr.models import init_mbr_tables
from mbr.certs.models import get_pipeline_wyniki_flat


@pytest.fixture
def db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_mbr_tables(c)
    c.execute(
        "INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, etapy_json, dt_utworzenia) "
        "VALUES (1, 'Chegina_K7', 1, 'active', '[]', '2026-04-23T00:00:00')"
    )
    c.execute(
        "INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, status, dt_start, pakowanie_bezposrednie) "
        "VALUES (100, 1, 'K7-PAK-1', 'K7/PAK-1', 'open', '2026-04-23T09:00:00', 'IBC')"
    )
    c.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
              "VALUES (20, 'standaryzacja', 'Standaryzacja', 'cykliczny')")
    # Two rounds under the same etap (cyclic stage) — real-world shape
    c.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, dt_start) "
              "VALUES (2000, 100, 20, 1, 'zamkniety', '2026-04-23T10:00:00')")
    c.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, dt_start) "
              "VALUES (2001, 100, 20, 2, 'zamkniety', '2026-04-23T10:10:00')")
    c.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (501, 'ph_10proc', 'pH 10%', 'bezposredni')")
    c.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (502, 'so3', 'SO3', 'bezposredni')")
    # Round 1: ph_10proc=6.3, so3=0.02
    c.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, wpisal, dt_wpisu) "
              "VALUES (2000, 501, 6.3, 'lab1', '2026-04-23T10:05:00')")
    c.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, wpisal, dt_wpisu) "
              "VALUES (2000, 502, 0.02, 'lab1', '2026-04-23T10:20:00')")
    # Round 2: ph_10proc=6.5 (overrides) — latest dt_wpisu wins
    c.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, wpisal, dt_wpisu) "
              "VALUES (2001, 501, 6.5, 'lab1', '2026-04-23T10:15:00')")
    c.commit()
    yield c
    c.close()


def test_returns_latest_per_kod(db):
    wf = get_pipeline_wyniki_flat(db, ebr_id=100)
    assert set(wf.keys()) == {"ph_10proc", "so3"}
    assert wf["ph_10proc"]["wartosc"] == 6.5
    assert wf["so3"]["wartosc"] == 0.02


def test_empty_for_missing_ebr(db):
    assert get_pipeline_wyniki_flat(db, ebr_id=99999) == {}


def test_ignores_null_wartosc(db):
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (503, 'barwa_hz', 'Barwa', 'bezposredni')")
    db.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, wpisal, dt_wpisu) "
               "VALUES (2000, 503, NULL, 'lab1', '2026-04-23T10:25:00')")
    db.commit()
    wf = get_pipeline_wyniki_flat(db, ebr_id=100)
    assert "barwa_hz" not in wf
