"""PR3: _build_pole propagates opisowe_wartosci as a parsed list for jakosciowy."""

import json as _json
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


def _seed_jakosciowy(db, wartosci):
    pid = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision, opisowe_wartosci) "
        "VALUES ('zapach', 'Zapach', 'jakosciowy', 'lab', 0, ?)",
        (_json.dumps(wartosci) if wartosci else None,),
    ).lastrowid
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('P', 'P')")
    eid = db.execute(
        "INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu) VALUES ('e1', 'Etap', 'jednorazowy')"
    ).lastrowid
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('P', ?, 1)", (eid,))
    db.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, grupa) VALUES (?, ?, 1, 'lab')", (eid, pid))
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, dla_szarzy, grupa) "
        "VALUES ('P', ?, ?, 1, 'lab')", (eid, pid),
    )
    db.commit()
    return pid


def test_build_pole_includes_opisowe_wartosci_as_list(db):
    from mbr.pipeline.adapter import build_pipeline_context
    _seed_jakosciowy(db, ["charakterystyczny", "obcy", "brak"])
    ctx = build_pipeline_context(db, "P", typ="szarza")
    pola = [p for s in ctx["parametry_lab"].values() for p in s["pola"]]
    assert len(pola) == 1
    assert pola[0]["opisowe_wartosci"] == ["charakterystyczny", "obcy", "brak"]


def test_build_pole_opisowe_wartosci_empty_when_null(db):
    from mbr.pipeline.adapter import build_pipeline_context
    _seed_jakosciowy(db, None)
    ctx = build_pipeline_context(db, "P", typ="szarza")
    pola = [p for s in ctx["parametry_lab"].values() for p in s["pola"]]
    assert pola[0]["opisowe_wartosci"] == []


def test_build_pole_no_opisowe_wartosci_key_for_non_jakosciowy(db):
    """Non-jakosciowy params don't get the key at all (keeps dict lean)."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision) "
        "VALUES ('gestosc', 'Gęstość', 'bezposredni', 'lab', 2)"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('P', 'P')")
    eid = db.execute(
        "INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu) VALUES ('e1', 'Etap', 'jednorazowy')"
    ).lastrowid
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('P', ?, 1)", (eid,))
    db.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, grupa) "
        "VALUES (?, (SELECT id FROM parametry_analityczne WHERE kod='gestosc'), 1, 'lab')",
        (eid,),
    )
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, dla_szarzy, grupa) "
        "VALUES ('P', ?, (SELECT id FROM parametry_analityczne WHERE kod='gestosc'), 1, 'lab')",
        (eid,),
    )
    db.commit()
    from mbr.pipeline.adapter import build_pipeline_context
    ctx = build_pipeline_context(db, "P", typ="szarza")
    pola = [p for s in ctx["parametry_lab"].values() for p in s["pola"]]
    assert "opisowe_wartosci" not in pola[0]
