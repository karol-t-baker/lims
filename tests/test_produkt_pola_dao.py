"""Tests for produkt_pola DAO and schema."""
import json
import sqlite3
import pytest
from mbr.models import init_mbr_tables
from mbr.shared import produkt_pola as pp


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


# ---------------------------------------------------------------------------
# DAO tests (Task 3)
# ---------------------------------------------------------------------------


@pytest.fixture
def db_with_produkt(db):
    db.execute("INSERT INTO produkty (id, nazwa, kod, aktywny) VALUES (9001, 'Monamid_KO_test', 'MKO_T', 1)")
    db.execute("INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
               "VALUES (9001, 'Test', 'User', 'TU_t', 'TU_t', 1)")
    db.commit()
    return db


def test_create_pole_minimal(db_with_produkt):
    pole_id = pp.create_pole(db_with_produkt, {
        "scope": "produkt",
        "scope_id": 9001,
        "kod": "nr_zamowienia",
        "label_pl": "Nr zamówienia",
        "typ_danych": "text",
        "miejsca": ["modal", "hero", "ukonczone"],
    }, user_id=9001)
    db_with_produkt.commit()
    row = db_with_produkt.execute("SELECT * FROM produkt_pola WHERE id=?", (pole_id,)).fetchone()
    assert row["kod"] == "nr_zamowienia"
    assert row["label_pl"] == "Nr zamówienia"
    assert row["aktywne"] == 1
    assert json.loads(row["miejsca"]) == ["modal", "hero", "ukonczone"]
    assert row["typy_rejestracji"] is None


def test_create_pole_with_typy_rejestracji(db_with_produkt):
    pole_id = pp.create_pole(db_with_produkt, {
        "scope": "produkt",
        "scope_id": 9001,
        "kod": "ilosc_konserwantuna",
        "label_pl": "Ilość konserwantuna",
        "typ_danych": "number",
        "jednostka": "kg",
        "miejsca": ["hero", "ukonczone"],
        "typy_rejestracji": ["zbiornik"],
    }, user_id=9001)
    db_with_produkt.commit()
    row = db_with_produkt.execute("SELECT * FROM produkt_pola WHERE id=?", (pole_id,)).fetchone()
    assert json.loads(row["typy_rejestracji"]) == ["zbiornik"]
    assert row["jednostka"] == "kg"


def test_create_pole_invalid_kod_regex(db_with_produkt):
    with pytest.raises(ValueError, match="kod"):
        pp.create_pole(db_with_produkt, {
            "scope": "produkt", "scope_id": 9001,
            "kod": "Nr Zamówienia",  # spaces, uppercase, special chars
            "label_pl": "X", "typ_danych": "text", "miejsca": [],
        }, user_id=9001)


def test_create_pole_cert_variant_requires_wartosc_stala(db_with_produkt):
    db_with_produkt.execute(
        "INSERT INTO cert_variants (id, produkt, variant_id, label) "
        "VALUES (9010, 'Chegina_K40GLOLMB', 'kosmepol_test', 'Kosmepol')"
    )
    db_with_produkt.commit()
    with pytest.raises(ValueError, match="wartosc_stala"):
        pp.create_pole(db_with_produkt, {
            "scope": "cert_variant", "scope_id": 9010,
            "kod": "nr_zam_kosmepol", "label_pl": "Nr zam. Kosmepol",
            "typ_danych": "text",
            # wartosc_stala missing → for active scope=cert_variant must error
            "aktywne": 1,
        }, user_id=9001)


def test_update_pole(db_with_produkt):
    pid = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 9001, "kod": "k1",
        "label_pl": "Stary", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=9001)
    db_with_produkt.commit()
    pp.update_pole(db_with_produkt, pid, {"label_pl": "Nowy", "kolejnosc": 5}, user_id=9001)
    db_with_produkt.commit()
    row = db_with_produkt.execute("SELECT label_pl, kolejnosc FROM produkt_pola WHERE id=?", (pid,)).fetchone()
    assert row["label_pl"] == "Nowy"
    assert row["kolejnosc"] == 5


def test_update_pole_kod_immutable(db_with_produkt):
    pid = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 9001, "kod": "stary_kod",
        "label_pl": "L", "typ_danych": "text", "miejsca": [],
    }, user_id=9001)
    db_with_produkt.commit()
    with pytest.raises(ValueError, match="kod.*immutable"):
        pp.update_pole(db_with_produkt, pid, {"kod": "nowy_kod"}, user_id=9001)


def test_deactivate_pole(db_with_produkt):
    pid = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 9001, "kod": "k1",
        "label_pl": "L", "typ_danych": "text", "miejsca": [],
    }, user_id=9001)
    db_with_produkt.commit()
    pp.deactivate_pole(db_with_produkt, pid, user_id=9001)
    db_with_produkt.commit()
    row = db_with_produkt.execute("SELECT aktywne FROM produkt_pola WHERE id=?", (pid,)).fetchone()
    assert row["aktywne"] == 0


def test_audit_event_emitted_on_create(db_with_produkt, monkeypatch):
    captured = []
    from mbr.shared import audit
    real_log = audit.log_event

    def fake_log(event_type, **kwargs):
        captured.append((event_type, kwargs))
        return real_log(event_type, **kwargs)

    monkeypatch.setattr(audit, "log_event", fake_log)
    # Re-bind in DAO module too — DAO imported `audit` then calls audit.log_event,
    # so monkeypatching the audit module attribute is sufficient.
    pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 9001, "kod": "k1",
        "label_pl": "L", "typ_danych": "text", "miejsca": [],
    }, user_id=9001)
    assert any(et == audit.EVENT_PRODUKT_POLA_CREATED for et, _ in captured)


# ---------------------------------------------------------------------------
# DAO tests for set_wartosc / get_wartosci_for_ebr (Task 4)
# ---------------------------------------------------------------------------


def test_set_wartosc_text(db_with_produkt):
    db_with_produkt.execute("INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, etapy_json, "
                            "parametry_lab, utworzony_przez, dt_utworzenia) "
                            "VALUES (9001, 'Monamid_KO_test', 1, 'active', '[]', '{}', 'tester', '2026-05-02')")
    db_with_produkt.execute("INSERT INTO ebr_batches (ebr_id, batch_id, mbr_id, nr_partii, dt_start, status) "
                            "VALUES (9001, 'B1_t', 9001, '001_t', '2026-05-02', 'open')")
    pid = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 9001, "kod": "nr_zam",
        "label_pl": "Nr", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=9001)
    db_with_produkt.commit()
    pp.set_wartosc(db_with_produkt, ebr_id=9001, pole_id=pid, wartosc="ZAM/123", user_id=9001)
    db_with_produkt.commit()
    row = db_with_produkt.execute(
        "SELECT wartosc FROM ebr_pola_wartosci WHERE ebr_id=9001 AND pole_id=?", (pid,)
    ).fetchone()
    assert row["wartosc"] == "ZAM/123"


def test_set_wartosc_number_normalizes_comma(db_with_produkt):
    db_with_produkt.execute("INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, etapy_json, "
                            "parametry_lab, utworzony_przez, dt_utworzenia) "
                            "VALUES (9001, 'Monamid_KO_test', 1, 'active', '[]', '{}', 'tester', '2026-05-02')")
    db_with_produkt.execute("INSERT INTO ebr_batches (ebr_id, batch_id, mbr_id, nr_partii, dt_start, status) "
                            "VALUES (9001, 'B1_t', 9001, '001_t', '2026-05-02', 'open')")
    pid = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 9001, "kod": "ilosc",
        "label_pl": "I", "typ_danych": "number", "miejsca": ["hero"],
    }, user_id=9001)
    db_with_produkt.commit()
    pp.set_wartosc(db_with_produkt, ebr_id=9001, pole_id=pid, wartosc="12.5", user_id=9001)
    db_with_produkt.commit()
    val = db_with_produkt.execute(
        "SELECT wartosc FROM ebr_pola_wartosci WHERE ebr_id=9001 AND pole_id=?", (pid,)
    ).fetchone()["wartosc"]
    # Polish convention: storage uses comma
    assert val == "12,5"
    # accept comma input too
    pp.set_wartosc(db_with_produkt, ebr_id=9001, pole_id=pid, wartosc="14,75", user_id=9001)
    db_with_produkt.commit()
    val = db_with_produkt.execute(
        "SELECT wartosc FROM ebr_pola_wartosci WHERE ebr_id=9001 AND pole_id=?", (pid,)
    ).fetchone()["wartosc"]
    assert val == "14,75"


def test_set_wartosc_number_invalid(db_with_produkt):
    db_with_produkt.execute("INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, etapy_json, "
                            "parametry_lab, utworzony_przez, dt_utworzenia) "
                            "VALUES (9001, 'Monamid_KO_test', 1, 'active', '[]', '{}', 'tester', '2026-05-02')")
    db_with_produkt.execute("INSERT INTO ebr_batches (ebr_id, batch_id, mbr_id, nr_partii, dt_start, status) "
                            "VALUES (9001, 'B1_t', 9001, '001_t', '2026-05-02', 'open')")
    pid = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 9001, "kod": "ilosc",
        "label_pl": "I", "typ_danych": "number", "miejsca": ["hero"],
    }, user_id=9001)
    db_with_produkt.commit()
    with pytest.raises(ValueError):
        pp.set_wartosc(db_with_produkt, ebr_id=9001, pole_id=pid, wartosc="abc", user_id=9001)


def test_set_wartosc_null_clears(db_with_produkt):
    db_with_produkt.execute("INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, etapy_json, "
                            "parametry_lab, utworzony_przez, dt_utworzenia) "
                            "VALUES (9001, 'X_t', 1, 'active', '[]', '{}', 'tester', '2026-05-02')")
    db_with_produkt.execute("INSERT INTO ebr_batches (ebr_id, batch_id, mbr_id, nr_partii, dt_start, status) "
                            "VALUES (9001, 'B1_t', 9001, '001_t', '2026-05-02', 'open')")
    pid = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 9001, "kod": "k",
        "label_pl": "L", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=9001)
    db_with_produkt.commit()
    pp.set_wartosc(db_with_produkt, 9001, pid, "X", user_id=9001)
    pp.set_wartosc(db_with_produkt, 9001, pid, None, user_id=9001)
    db_with_produkt.commit()
    val = db_with_produkt.execute(
        "SELECT wartosc FROM ebr_pola_wartosci WHERE ebr_id=9001 AND pole_id=?", (pid,)
    ).fetchone()["wartosc"]
    assert val is None


def test_get_wartosci_for_ebr_returns_dict(db_with_produkt):
    db_with_produkt.execute("INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, etapy_json, "
                            "parametry_lab, utworzony_przez, dt_utworzenia) "
                            "VALUES (9001, 'Monamid_KO_test', 1, 'active', '[]', '{}', 'tester', '2026-05-02')")
    db_with_produkt.execute("INSERT INTO ebr_batches (ebr_id, batch_id, mbr_id, nr_partii, dt_start, status) "
                            "VALUES (9001, 'B1_t', 9001, '001_t', '2026-05-02', 'open')")
    p1 = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 9001, "kod": "nr_zam",
        "label_pl": "Nr", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=9001)
    p2 = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 9001, "kod": "nr_dop",
        "label_pl": "Dop", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=9001)
    pp.set_wartosc(db_with_produkt, 9001, p1, "ZAM/1", user_id=9001)
    pp.set_wartosc(db_with_produkt, 9001, p2, "DOP/2", user_id=9001)
    db_with_produkt.commit()
    result = pp.get_wartosci_for_ebr(db_with_produkt, ebr_id=9001, produkt_id=9001)
    assert result == {"nr_zam": "ZAM/1", "nr_dop": "DOP/2"}
