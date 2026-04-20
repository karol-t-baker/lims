"""PR2: create_ebr auto-inserts ebr_wyniki.wartosc_text for typ='jakosciowy' params."""

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


def _seed_product_with_jakosciowy(db, produkt="P2", kod="zapach",
                                   cert_qr="charakterystyczny"):
    """Seed product + MBR with one jakosciowy param that has cert_qualitative_result set."""
    pid = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision, opisowe_wartosci) "
        "VALUES (?, ?, 'jakosciowy', 'lab', 0, ?)",
        (kod, kod.capitalize(), _json.dumps(["charakterystyczny", "obcy"])),
    ).lastrowid
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES (?, ?)", (produkt, produkt))
    # Use etapy_analityczne (actual table name per PR2-T3 findings).
    eid = db.execute(
        "INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu) VALUES ('e1', 'Etap 1', 'jednorazowy')"
    ).lastrowid
    db.execute(
        "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES (?, ?, 1)",
        (produkt, eid),
    )
    db.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, grupa) "
        "VALUES (?, ?, 1, 'lab')",
        (eid, pid),
    )
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
        "dla_szarzy, grupa) VALUES (?, ?, ?, 1, 'lab')",
        (produkt, eid, pid),
    )
    # Default value source — seed parametry_etapy with cert_qualitative_result
    db.execute(
        "INSERT INTO parametry_etapy (produkt, kontekst, parametr_id, "
        "cert_qualitative_result, on_cert) VALUES (?, 'e1', ?, ?, 1)",
        (produkt, pid, cert_qr),
    )
    # Active MBR template (create_ebr reads active MBR)
    from mbr.parametry.registry import build_parametry_lab
    plab = _json.dumps(build_parametry_lab(db, produkt), ensure_ascii=False)
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, parametry_lab, etapy_json, dt_utworzenia) "
        "VALUES (?, 1, 'active', ?, '[]', '2026-01-01')",
        (produkt, plab),
    )
    db.commit()
    return pid


def test_create_ebr_autoinserts_jakosciowy_with_cert_default(db):
    from mbr.laborant.models import create_ebr
    _seed_product_with_jakosciowy(db, cert_qr="charakterystyczny")
    ebr_id = create_ebr(db, "P2", "1", "A", "M", 100, "lab_test", typ="szarza")
    assert ebr_id is not None
    rows = db.execute(
        "SELECT kod_parametru, wartosc, wartosc_text FROM ebr_wyniki WHERE ebr_id=?",
        (ebr_id,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["kod_parametru"] == "zapach"
    assert rows[0]["wartosc"] is None
    assert rows[0]["wartosc_text"] == "charakterystyczny"


def test_create_ebr_skips_jakosciowy_when_cert_default_empty(db):
    from mbr.laborant.models import create_ebr
    _seed_product_with_jakosciowy(db, cert_qr=None)
    ebr_id = create_ebr(db, "P2", "2", "A", "M", 100, "lab_test", typ="szarza")
    rows = db.execute(
        "SELECT * FROM ebr_wyniki WHERE ebr_id=?", (ebr_id,)
    ).fetchall()
    assert len(rows) == 0


def test_create_ebr_skips_non_jakosciowy_params(db):
    """bezposredni params are NOT auto-inserted (laborant fills them manually)."""
    from mbr.laborant.models import create_ebr
    pid = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision) "
        "VALUES ('gestosc', 'Gęstość', 'bezposredni', 'lab', 2)"
    ).lastrowid
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('P3', 'P3')")
    eid = db.execute(
        "INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu) VALUES ('e1', 'Etap 1', 'jednorazowy')"
    ).lastrowid
    db.execute(
        "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('P3', ?, 1)",
        (eid,),
    )
    db.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, grupa) "
        "VALUES (?, ?, 1, 'lab')",
        (eid, pid),
    )
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
        "dla_szarzy, grupa) VALUES ('P3', ?, ?, 1, 'lab')",
        (eid, pid),
    )
    from mbr.parametry.registry import build_parametry_lab
    plab = _json.dumps(build_parametry_lab(db, "P3"), ensure_ascii=False)
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, parametry_lab, etapy_json, dt_utworzenia) "
        "VALUES ('P3', 1, 'active', ?, '[]', '2026-01-01')",
        (plab,),
    )
    db.commit()
    ebr_id = create_ebr(db, "P3", "1", "A", "M", 100, "lab_test", typ="szarza")
    rows = db.execute(
        "SELECT * FROM ebr_wyniki WHERE ebr_id=?", (ebr_id,)
    ).fetchall()
    assert len(rows) == 0
