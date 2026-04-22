import sqlite3
import pytest

from mbr.models import init_mbr_tables
from mbr.pipeline.edit_policy import is_sesja_editable, has_downstream_activity


def _seed(db):
    db.execute(
        "INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, etapy_json, dt_utworzenia) "
        "VALUES (1, 'Chegina_K7', 1, 'active', '[]', '2026-04-22T00:00:00')"
    )
    db.execute(
        "INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, status, dt_start) "
        "VALUES (100, 1, 'K7-TEST-0001', 'K7/TEST', 'open', '2026-04-22T09:00:00')"
    )
    db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
               "VALUES (10, 'sulfonowanie', 'Sulfonowanie', 'cykliczny')")
    db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
               "VALUES (11, 'analiza_koncowa', 'Analiza końcowa', 'jednorazowy')")
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chegina_K7', 10, 1)")
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chegina_K7', 11, 2)")
    db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, dt_start) "
               "VALUES (1000, 100, 10, 1, 'zamkniety', '2026-04-22T10:00:00')")
    db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, dt_start) "
               "VALUES (1001, 100, 11, 1, 'zamkniety', '2026-04-22T12:00:00')")
    db.commit()


@pytest.fixture
def db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_mbr_tables(c)
    _seed(c)
    yield c
    c.close()


def test_open_batch_any_closed_sesja_editable(db):
    """Batch open → closed sulfonowanie is editable."""
    assert is_sesja_editable(db, ebr_id=100, sesja_id=1000) is True


def test_open_batch_last_stage_editable(db):
    """Batch open → closed analiza_koncowa is editable."""
    assert is_sesja_editable(db, ebr_id=100, sesja_id=1001) is True


def test_closed_batch_last_stage_editable(db):
    """Batch completed → only last stage (analiza_koncowa) editable."""
    db.execute("UPDATE ebr_batches SET status='completed' WHERE ebr_id=100")
    db.commit()
    assert is_sesja_editable(db, ebr_id=100, sesja_id=1001) is True


def test_closed_batch_earlier_stage_not_editable(db):
    """Batch completed → sulfonowanie NOT editable."""
    db.execute("UPDATE ebr_batches SET status='completed' WHERE ebr_id=100")
    db.commit()
    assert is_sesja_editable(db, ebr_id=100, sesja_id=1000) is False


def test_missing_sesja_not_editable(db):
    assert is_sesja_editable(db, ebr_id=100, sesja_id=9999) is False


def test_downstream_detects_later_pomiar(db):
    # id=777 to avoid collision with auto-seeded parametry (e.g. nadtlenki at id=1).
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (777, 'x', 'X', 'bezposredni')")
    db.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, wpisal, dt_wpisu) "
               "VALUES (1001, 777, 5.0, 'u', '2026-04-22T12:00:00')")
    db.commit()
    # Editing sulfonowanie (etap 10) while analiza_koncowa (etap 11) has a pomiar → downstream exists.
    info = has_downstream_activity(db, ebr_id=100, etap_id=10)
    assert info["has_downstream"] is True
    assert any(s["etap_id"] == 11 and s["pomiary"] >= 1 for s in info["stages"])


def test_downstream_none_for_last_stage(db):
    """Last stage never has downstream."""
    info = has_downstream_activity(db, ebr_id=100, etap_id=11)
    assert info["has_downstream"] is False
    assert info["stages"] == []
