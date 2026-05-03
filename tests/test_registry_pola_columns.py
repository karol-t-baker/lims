"""Registry models — dynamic produkt_pola columns + per-batch values."""
import sqlite3

import pytest

from mbr.models import init_mbr_tables
from mbr.shared import produkt_pola as pp
from mbr.registry import models as reg
from mbr.shared.timezone import app_now_iso


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (9001, 'T', 'U', 'TU_r', 'TU_r', 1)"
    )
    conn.execute(
        "INSERT INTO produkty (id, nazwa, kod, aktywny) "
        "VALUES (9001, 'Monamid_KO_r', 'MKO_r', 1)"
    )
    conn.execute(
        "INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, etapy_json, "
        "parametry_lab, utworzony_przez, dt_utworzenia) "
        "VALUES (9001, 'Monamid_KO_r', 1, 'active', '[]', '{}', 'tester', '2026-05-02')"
    )
    now = app_now_iso()
    conn.execute(
        "INSERT INTO ebr_batches (ebr_id, batch_id, mbr_id, nr_partii, dt_start, "
        "dt_end, status, typ) "
        "VALUES (9001, 'Monamid_KO_r__001r', 9001, '001r', ?, ?, 'completed', 'szarza')",
        (now, now),
    )
    conn.commit()
    yield conn
    conn.close()


def test_list_completed_includes_pola_dict(db):
    pid = pp.create_pole(db, {
        "scope": "produkt", "scope_id": 9001, "kod": "nr_zam",
        "label_pl": "Nr zamowienia", "typ_danych": "text",
        "miejsca": ["ukonczone"],
    }, user_id=9001)
    pp.set_wartosc(db, 9001, pid, "ZAM/777", user_id=9001)
    db.commit()
    rows = reg.list_completed_registry(db, produkt="Monamid_KO_r")
    assert len(rows) == 1
    assert rows[0]["ebr_id"] == 9001
    assert rows[0]["pola"] == {"nr_zam": "ZAM/777"}


def test_list_completed_pola_empty_when_no_definitions(db):
    rows = reg.list_completed_registry(db, produkt="Monamid_KO_r")
    assert len(rows) == 1
    assert rows[0]["pola"] == {}


def test_get_registry_columns_includes_dynamic(db):
    pp.create_pole(db, {
        "scope": "produkt", "scope_id": 9001, "kod": "nr_zam",
        "label_pl": "Nr zamowienia", "typ_danych": "text",
        "miejsca": ["ukonczone"],
    }, user_id=9001)
    pp.create_pole(db, {
        "scope": "produkt", "scope_id": 9001, "kod": "ilosc_k",
        "label_pl": "Ilosc konserwantu", "typ_danych": "number",
        "jednostka": "kg",
        "miejsca": ["ukonczone"],
    }, user_id=9001)
    db.commit()
    cols = reg.get_registry_columns(db, "Monamid_KO_r")
    keys = [c.get("kod") for c in cols]
    assert "pola.nr_zam" in keys
    assert "pola.ilosc_k" in keys
    nr_col = next(c for c in cols if c.get("kod") == "pola.nr_zam")
    assert nr_col["label"] == "Nr zamowienia"
    assert nr_col.get("is_pola") is True
    ilosc_col = next(c for c in cols if c.get("kod") == "pola.ilosc_k")
    assert ilosc_col["label"] == "Ilosc konserwantu [kg]"


def test_get_registry_columns_excludes_inactive(db):
    pid = pp.create_pole(db, {
        "scope": "produkt", "scope_id": 9001, "kod": "wylaczone",
        "label_pl": "W", "typ_danych": "text",
        "miejsca": ["ukonczone"],
    }, user_id=9001)
    pp.deactivate_pole(db, pid, user_id=9001)
    db.commit()
    cols = reg.get_registry_columns(db, "Monamid_KO_r")
    keys = [c.get("kod") for c in cols]
    assert "pola.wylaczone" not in keys


def test_get_registry_columns_excludes_pola_without_ukonczone(db):
    """Pola not in 'ukonczone' miejsca should NOT show as columns."""
    pp.create_pole(db, {
        "scope": "produkt", "scope_id": 9001, "kod": "modal_only",
        "label_pl": "M", "typ_danych": "text",
        "miejsca": ["modal"],
    }, user_id=9001)
    db.commit()
    cols = reg.get_registry_columns(db, "Monamid_KO_r")
    keys = [c.get("kod") for c in cols]
    assert "pola.modal_only" not in keys


def test_get_registry_columns_filters_by_produkt(db):
    """Only pola defined for THIS produkt should appear in its columns."""
    db.execute(
        "INSERT INTO produkty (id, nazwa, kod, aktywny) "
        "VALUES (9002, 'Monamid_INNE_r', 'MIN_r', 1)"
    )
    db.commit()
    pp.create_pole(db, {
        "scope": "produkt", "scope_id": 9002, "kod": "obcy",
        "label_pl": "Obcy", "typ_danych": "text",
        "miejsca": ["ukonczone"],
    }, user_id=9001)
    pp.create_pole(db, {
        "scope": "produkt", "scope_id": 9001, "kod": "wlasny",
        "label_pl": "Wlasny", "typ_danych": "text",
        "miejsca": ["ukonczone"],
    }, user_id=9001)
    db.commit()
    cols = reg.get_registry_columns(db, "Monamid_KO_r")
    keys = [c.get("kod") for c in cols]
    assert "pola.wlasny" in keys
    assert "pola.obcy" not in keys
