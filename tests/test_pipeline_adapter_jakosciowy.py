"""PR2: propagate parametry_analityczne.typ into pole dict as typ_analityczny."""

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


def _seed_product_with_param(db, produkt="TESTPROD", kod="zapach", typ="jakosciowy",
                              grupa="lab", opisowe_wartosci=None):
    """Seed minimal pipeline so build_pipeline_context returns at least one pole."""
    import json as _json
    pid = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision, opisowe_wartosci) "
        "VALUES (?, ?, ?, ?, 0, ?)",
        (kod, kod.capitalize(), typ, grupa,
         _json.dumps(opisowe_wartosci) if opisowe_wartosci else None),
    ).lastrowid
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES (?, ?)", (produkt, produkt))
    eid = db.execute(
        "INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu) VALUES ('e1', 'Etap 1', 'jednorazowy')"
    ).lastrowid
    db.execute(
        "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) "
        "VALUES (?, ?, 1)",
        (produkt, eid),
    )
    db.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, grupa) "
        "VALUES (?, ?, 1, ?)",
        (eid, pid, grupa),
    )
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
        "dla_szarzy, dla_zbiornika, dla_platkowania, grupa) "
        "VALUES (?, ?, ?, 1, 0, 0, ?)",
        (produkt, eid, pid, grupa),
    )
    db.commit()
    return pid, eid


def test_build_pole_includes_typ_analityczny(db):
    """_build_pole exposes the raw parametry_analityczne.typ value as 'typ_analityczny'."""
    from mbr.pipeline.adapter import build_pipeline_context
    _seed_product_with_param(db, typ="jakosciowy",
                             opisowe_wartosci=["charakterystyczny", "obcy"])
    ctx = build_pipeline_context(db, "TESTPROD", typ="szarza")
    assert ctx is not None
    pola = []
    for sekcja in ctx["parametry_lab"].values():
        pola.extend(sekcja["pola"])
    assert len(pola) == 1
    assert pola[0]["typ_analityczny"] == "jakosciowy"


def test_build_pole_typ_analityczny_for_bezposredni(db):
    _seed_product_with_param(db, kod="gestosc", typ="bezposredni")
    from mbr.pipeline.adapter import build_pipeline_context
    ctx = build_pipeline_context(db, "TESTPROD", typ="szarza")
    assert ctx is not None
    pola = []
    for sekcja in ctx["parametry_lab"].values():
        pola.extend(sekcja["pola"])
    assert pola[0]["typ_analityczny"] == "bezposredni"


def test_filter_hides_jakosciowy_and_zewn():
    """filter_parametry_lab_for_entry keeps only grupa='lab' AND typ != 'jakosciowy'."""
    from mbr.pipeline.adapter import filter_parametry_lab_for_entry
    parametry_lab = {
        "analiza": {"label": "Analiza", "pola": [
            {"kod": "gestosc", "grupa": "lab", "typ_analityczny": "bezposredni"},
            {"kod": "zapach", "grupa": "lab", "typ_analityczny": "jakosciowy"},
            {"kod": "siarka", "grupa": "zewn", "typ_analityczny": "bezposredni"},
            {"kod": "ph", "grupa": "lab", "typ_analityczny": "titracja"},
        ]},
        "standaryzacja": {"label": "Std", "pola": [
            {"kod": "x_zewn", "grupa": "zewn", "typ_analityczny": "bezposredni"},
        ]},
    }
    filtered = filter_parametry_lab_for_entry(parametry_lab)
    analiza_kody = [p["kod"] for p in filtered["analiza"]["pola"]]
    assert analiza_kody == ["gestosc", "ph"]
    assert "standaryzacja" not in filtered


def test_filter_preserves_empty_input():
    from mbr.pipeline.adapter import filter_parametry_lab_for_entry
    assert filter_parametry_lab_for_entry({}) == {}


def test_filter_treats_missing_grupa_as_lab():
    """Legacy fields without explicit grupa should be treated as lab."""
    from mbr.pipeline.adapter import filter_parametry_lab_for_entry
    parametry_lab = {
        "analiza": {"label": "Analiza", "pola": [
            {"kod": "gestosc", "typ_analityczny": "bezposredni"},
        ]},
    }
    filtered = filter_parametry_lab_for_entry(parametry_lab)
    assert len(filtered["analiza"]["pola"]) == 1


def test_filter_treats_missing_typ_analityczny_as_non_jakosciowy():
    """Fields without typ_analityczny (pre-PR2 snapshots) default to visible."""
    from mbr.pipeline.adapter import filter_parametry_lab_for_entry
    parametry_lab = {
        "analiza": {"label": "Analiza", "pola": [
            {"kod": "legacy", "grupa": "lab"},
        ]},
    }
    filtered = filter_parametry_lab_for_entry(parametry_lab)
    assert len(filtered["analiza"]["pola"]) == 1
