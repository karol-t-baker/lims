"""Integration test: operator-driven flow through sulfonowanie → utlenianie → standaryzacja."""
import sqlite3
import pytest
from mbr.models import init_mbr_tables
from mbr.pipeline.models import (
    create_sesja, save_pomiar, create_zlecenie_korekty,
    wykonaj_zlecenie, get_zlecenie, resolve_limity,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def pipeline(db):
    """Set up 3-stage pipeline: sulfonowanie → utlenianie → standaryzacja."""
    db.execute("INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu) VALUES ('sulfonowanie','Sulfonowanie','cykliczny')")
    db.execute("INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu) VALUES ('utlenianie','Utlenianie','cykliczny')")
    db.execute("INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu) VALUES ('standaryzacja','Standaryzacja','cykliczny')")

    sulf_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='sulfonowanie'").fetchone()["id"]
    utl_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='utlenianie'").fetchone()["id"]
    std_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='standaryzacja'").fetchone()["id"]

    db.execute("INSERT INTO parametry_analityczne (kod, label, typ, jednostka) VALUES ('so3','SO3','oznaczeniowy','%')")
    so3_id = db.execute("SELECT id FROM parametry_analityczne WHERE kod='so3'").fetchone()["id"]

    db.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, spec_value) VALUES (?,?,1,12.0)", (sulf_id, so3_id))

    db.execute("INSERT INTO etap_korekty_katalog (etap_id, substancja, jednostka, kolejnosc) VALUES (?,'Na2SO3','kg',1)", (sulf_id,))
    na2so3_id = db.execute("SELECT id FROM etap_korekty_katalog WHERE substancja='Na2SO3'").fetchone()["id"]

    # ebr_batches requires mbr_id FK → mbr_templates
    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia) VALUES (1, 'K40GLO', 1, '2026-01-01')")
    db.execute("INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start) VALUES (1, 1, 'TEST-001', '1/2026', '2026-01-01')")
    ebr_id = 1

    db.commit()
    return {
        "ebr_id": ebr_id, "sulf_id": sulf_id, "utl_id": utl_id, "std_id": std_id,
        "so3_id": so3_id, "na2so3_id": na2so3_id,
    }


def test_full_operator_flow(db, pipeline):
    """Operator flow: sulfonowanie oznaczenie → korekta → runda 2 → zamknij → utlenianie."""
    p = pipeline

    # Runda 1: oznaczenie SO3 = 10.0 (below spec 12.0)
    sesja1 = create_sesja(db, p["ebr_id"], p["sulf_id"], runda=1, laborant="lab1")
    save_pomiar(db, sesja1, p["so3_id"], wartosc=10.0, min_limit=None, max_limit=None, wpisal="lab1")
    db.commit()

    sesja_row = db.execute("SELECT status FROM ebr_etap_sesja WHERE id=?", (sesja1,)).fetchone()
    # Default status from DB is 'nierozpoczety'; operator updates it as work begins
    assert sesja_row["status"] in ("nierozpoczety", "w_trakcie")

    # Operator orders correction: Na2SO3 5kg
    zlecenie_id = create_zlecenie_korekty(
        db, sesja1,
        items=[{"korekta_typ_id": p["na2so3_id"], "ilosc": 5.0, "ilosc_wyliczona": None}],
        zalecil="lab1",
    )
    db.commit()

    zlecenie = get_zlecenie(db, zlecenie_id)
    assert zlecenie["status"] == "zalecona"
    assert len(zlecenie["items"]) == 1

    # Correction executed → new session (runda 2)
    sesja2 = wykonaj_zlecenie(db, zlecenie_id)
    db.commit()

    sesja2_row = db.execute("SELECT * FROM ebr_etap_sesja WHERE id=?", (sesja2,)).fetchone()
    assert sesja2_row["runda"] == 2
    assert sesja2_row["status"] == "w_trakcie"

    # Runda 2: SO3 = 12.1 (in spec)
    save_pomiar(db, sesja2, p["so3_id"], wartosc=12.1, min_limit=None, max_limit=None, wpisal="lab1")
    db.commit()

    # Operator closes sulfonowanie
    db.execute("UPDATE ebr_etap_sesja SET status='zamkniety' WHERE id=?", (sesja2,))
    db.commit()

    sesja2_row = db.execute("SELECT status FROM ebr_etap_sesja WHERE id=?", (sesja2,)).fetchone()
    assert sesja2_row["status"] == "zamkniety"

    # Operator can reopen
    db.execute("UPDATE ebr_etap_sesja SET status='w_trakcie' WHERE id=?", (sesja2,))
    db.commit()
    sesja2_row = db.execute("SELECT status FROM ebr_etap_sesja WHERE id=?", (sesja2,)).fetchone()
    assert sesja2_row["status"] == "w_trakcie"

    # Operator starts utlenianie (free navigation)
    sesja_utl = create_sesja(db, p["ebr_id"], p["utl_id"], runda=1, laborant="lab1")
    db.commit()
    assert sesja_utl is not None


def test_resolve_limity_spec_value(db, pipeline):
    """resolve_limity returns spec_value, not target."""
    p = pipeline
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('K40GLO',?,1)", (p["sulf_id"],))
    db.commit()

    result = resolve_limity(db, "K40GLO", p["sulf_id"])
    assert len(result) > 0
    assert "spec_value" in result[0]
    assert result[0]["spec_value"] == 12.0
    assert "target" not in result[0]
