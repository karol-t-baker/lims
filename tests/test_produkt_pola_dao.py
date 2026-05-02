"""Tests for produkt_pola DAO and schema."""
import sqlite3
import pytest
from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    yield conn
    conn.close()


def test_schema_produkt_pola_table_exists(db):
    cols = {r["name"] for r in db.execute("PRAGMA table_info(produkt_pola)")}
    expected = {
        "id", "scope", "scope_id", "kod", "label_pl", "typ_danych",
        "jednostka", "wartosc_stala", "obowiazkowe", "miejsca",
        "typy_rejestracji", "kolejnosc", "aktywne",
        "created_at", "created_by", "updated_at", "updated_by",
    }
    assert expected.issubset(cols), f"Missing columns: {expected - cols}"


def test_schema_ebr_pola_wartosci_table_exists(db):
    cols = {r["name"] for r in db.execute("PRAGMA table_info(ebr_pola_wartosci)")}
    expected = {
        "id", "ebr_id", "pole_id", "wartosc",
        "created_at", "created_by", "updated_at", "updated_by",
    }
    assert expected.issubset(cols), f"Missing columns: {expected - cols}"


def test_unique_constraint_scope_scope_id_kod(db):
    # Use a high id to avoid colliding with rows seeded by init_mbr_tables.
    db.execute(
        "INSERT INTO produkty (id, nazwa, kod, aktywny) VALUES (9001, 'Test', 'TST', 1)"
    )
    db.execute(
        "INSERT INTO produkt_pola (scope, scope_id, kod, label_pl, typ_danych, miejsca) "
        "VALUES ('produkt', 9001, 'nr_zam', 'Nr zam.', 'text', '[]')"
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO produkt_pola (scope, scope_id, kod, label_pl, typ_danych, miejsca) "
            "VALUES ('produkt', 9001, 'nr_zam', 'Inne', 'text', '[]')"
        )
        db.commit()


def test_cascade_delete_pole_removes_wartosci(db):
    # Use high ids to avoid colliding with rows seeded by init_mbr_tables.
    # Note: ebr_batches PK column is `ebr_id` (not `id`).
    db.execute("INSERT INTO produkty (id, nazwa, kod, aktywny) VALUES (9001, 'Test', 'TST', 1)")
    cur = db.execute("INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
                     "utworzony_przez, dt_utworzenia) VALUES ('Test', 1, 'active', '[]', '{}', 't', '2026-05-02')")
    mbr_id = cur.lastrowid
    db.execute("INSERT INTO ebr_batches (ebr_id, batch_id, mbr_id, nr_partii, dt_start, status) "
               "VALUES (9001, 'B1', ?, '001', '2026-05-02', 'open')", (mbr_id,))
    db.execute("INSERT INTO produkt_pola (id, scope, scope_id, kod, label_pl, typ_danych, miejsca) "
               "VALUES (9001, 'produkt', 9001, 'k', 'L', 'text', '[]')")
    db.execute("INSERT INTO ebr_pola_wartosci (ebr_id, pole_id, wartosc) VALUES (9001, 9001, 'v')")
    db.commit()
    db.execute("DELETE FROM produkt_pola WHERE id=9001")
    db.commit()
    cnt = db.execute("SELECT COUNT(*) FROM ebr_pola_wartosci").fetchone()[0]
    assert cnt == 0
