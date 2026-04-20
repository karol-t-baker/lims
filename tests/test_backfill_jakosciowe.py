"""PR2: backfill_jakosciowe_values.py seeds ebr_wyniki for existing open batches."""

import json as _json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from mbr.models import init_mbr_tables


def _seed_open_ebr_with_jakosciowy(db_path, cert_qr="charakterystyczny"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    pid = conn.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision, opisowe_wartosci) "
        "VALUES ('zapach', 'Zapach', 'jakosciowy', 'lab', 0, ?)",
        (_json.dumps(["charakterystyczny"]),),
    ).lastrowid
    conn.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('PB', 'PB')")
    eid = conn.execute(
        "INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu) VALUES ('e1', 'Etap 1', 'jednorazowy')"
    ).lastrowid
    conn.execute(
        "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('PB', ?, 1)",
        (eid,),
    )
    conn.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, grupa) "
        "VALUES (?, ?, 1, 'lab')",
        (eid, pid),
    )
    conn.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
        "dla_szarzy, grupa) VALUES ('PB', ?, ?, 1, 'lab')",
        (eid, pid),
    )
    conn.execute(
        "INSERT INTO parametry_etapy (produkt, kontekst, parametr_id, "
        "cert_qualitative_result, on_cert) VALUES ('PB', 'e1', ?, ?, 1)",
        (pid, cert_qr),
    )
    from mbr.parametry.registry import build_parametry_lab
    plab = _json.dumps(build_parametry_lab(conn, "PB"), ensure_ascii=False)
    # NOTE: mbr_templates requires NOT NULL wersja and dt_utworzenia.
    mbr_id = conn.execute(
        "INSERT INTO mbr_templates (produkt, status, parametry_lab, etapy_json, "
        "wersja, dt_utworzenia) VALUES ('PB', 'active', ?, '[]', 1, '2026-01-01')",
        (plab,),
    ).lastrowid
    ebr_id = conn.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, nr_amidatora, "
        "nr_mieszalnika, wielkosc_szarzy_kg, dt_start, operator, typ, status) "
        "VALUES (?, 'PB__1', '1', 'A', 'M', 100, '2026-04-20', 'lab', 'szarza', 'open')",
        (mbr_id,),
    ).lastrowid
    conn.commit()
    conn.close()
    return ebr_id


def test_backfill_inserts_missing_jakosciowe_rows():
    from scripts import backfill_jakosciowe_values as bfj
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.sqlite"
        ebr_id = _seed_open_ebr_with_jakosciowy(db_path)
        inserted = bfj.run(str(db_path))
        assert inserted == 1
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT wartosc_text FROM ebr_wyniki WHERE ebr_id=?", (ebr_id,)
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0]["wartosc_text"] == "charakterystyczny"


def test_backfill_is_idempotent():
    from scripts import backfill_jakosciowe_values as bfj
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.sqlite"
        _seed_open_ebr_with_jakosciowy(db_path)
        first = bfj.run(str(db_path))
        second = bfj.run(str(db_path))
        assert first == 1
        assert second == 0


def test_backfill_skips_completed_batches():
    """Completed batches (status='completed') are out of scope for the backfill."""
    from scripts import backfill_jakosciowe_values as bfj
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.sqlite"
        _seed_open_ebr_with_jakosciowy(db_path)
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE ebr_batches SET status='completed'")
        conn.commit()
        conn.close()
        inserted = bfj.run(str(db_path))
        assert inserted == 0


def test_backfill_handles_empty_db():
    from scripts import backfill_jakosciowe_values as bfj
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.sqlite"
        conn = sqlite3.connect(db_path)
        init_mbr_tables(conn)
        conn.close()
        inserted = bfj.run(str(db_path))
        assert inserted == 0
