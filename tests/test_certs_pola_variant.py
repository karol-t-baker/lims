"""Generator certow — sub-namespace `pola.<kod>` z scope=cert_variant."""
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
    conn.execute(
        "INSERT INTO produkty (id, nazwa, kod, aktywny) "
        "VALUES (9001, 'Chegina_K40GLOLMB_c', 'K4_c', 1)"
    )
    conn.execute(
        "INSERT INTO cert_variants (id, produkt, variant_id, label) "
        "VALUES (9010, 'Chegina_K40GLOLMB_c', 'kosmepol_c', 'Kosmepol')"
    )
    conn.execute(
        "INSERT INTO cert_variants (id, produkt, variant_id, label) "
        "VALUES (9011, 'Chegina_K40GLOLMB_c', 'inny_c', 'Inny')"
    )
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (9001, 'T', 'U', 'TU_c', 'TU_c', 1)"
    )
    conn.commit()
    yield conn
    conn.close()


def test_build_pola_context_for_variant(db):
    pp.create_pole(db, {
        "scope": "cert_variant", "scope_id": 9010, "kod": "nr_zam_kosmepol",
        "label_pl": "Nr", "typ_danych": "text",
        "wartosc_stala": "KSM/2026/001",
    }, user_id=9001)
    db.commit()
    from mbr.certs import generator
    pola = generator.build_pola_context(db, variant_id=9010)
    assert pola == {"nr_zam_kosmepol": "KSM/2026/001"}


def test_build_pola_context_isolates_per_variant(db):
    pp.create_pole(db, {
        "scope": "cert_variant", "scope_id": 9010, "kod": "nr_zam_kosmepol",
        "label_pl": "Nr", "typ_danych": "text",
        "wartosc_stala": "KSM/A",
    }, user_id=9001)
    pp.create_pole(db, {
        "scope": "cert_variant", "scope_id": 9011, "kod": "nr_zam_inny",
        "label_pl": "Inny", "typ_danych": "text",
        "wartosc_stala": "INNY/B",
    }, user_id=9001)
    db.commit()
    from mbr.certs import generator
    pola_kosmepol = generator.build_pola_context(db, variant_id=9010)
    pola_inny = generator.build_pola_context(db, variant_id=9011)
    assert "nr_zam_kosmepol" in pola_kosmepol
    assert "nr_zam_inny" not in pola_kosmepol
    assert "nr_zam_inny" in pola_inny
    assert "nr_zam_kosmepol" not in pola_inny


def test_build_pola_context_excludes_inactive(db):
    pid = pp.create_pole(db, {
        "scope": "cert_variant", "scope_id": 9010, "kod": "wylaczone",
        "label_pl": "W", "typ_danych": "text",
        "wartosc_stala": "X",
    }, user_id=9001)
    pp.deactivate_pole(db, pid, user_id=9001)
    db.commit()
    from mbr.certs import generator
    pola = generator.build_pola_context(db, variant_id=9010)
    assert "wylaczone" not in pola


def test_build_pola_context_returns_empty_for_none(db):
    from mbr.certs import generator
    pola = generator.build_pola_context(db, variant_id=None)
    assert pola == {}


def test_build_pola_context_returns_empty_for_unknown_variant(db):
    from mbr.certs import generator
    pola = generator.build_pola_context(db, variant_id=99999)
    assert pola == {}


def test_build_context_includes_pola_subnamespace(db, monkeypatch):
    """build_context should expose `pola` sub-namespace from variant fields."""
    pp.create_pole(db, {
        "scope": "cert_variant", "scope_id": 9010, "kod": "nr_zam_kosmepol",
        "label_pl": "Nr", "typ_danych": "text",
        "wartosc_stala": "KSM/123",
    }, user_id=9001)
    db.commit()
    # Stub mbr.db.db_session to return our in-memory db
    from contextlib import contextmanager
    import mbr.db
    import mbr.certs.generator as gen

    @contextmanager
    def fake():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake)
    monkeypatch.setattr(gen, "load_config", lambda: {
        "company": {"name": "Test"},
        "footer": {},
        "rspo_number": "X",
    })

    ctx = gen.build_context(
        produkt="Chegina_K40GLOLMB_c",
        variant_id="kosmepol_c",
        nr_partii="001/2026",
        dt_start=None,
        wyniki_flat={},
    )
    assert "pola" in ctx
    assert ctx["pola"] == {"nr_zam_kosmepol": "KSM/123"}
