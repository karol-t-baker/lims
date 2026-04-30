"""Migration: clear stale cert_qualitative_result + flip grupa to 'zewn'
+ purge old single-value ebr_wyniki rows for cert_qual_rozklad_kwasow."""

import sqlite3
import pytest
from mbr.models import init_mbr_tables
from scripts.migrate_rozklad_kwasow_seed import run_migration


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed_baseline(db):
    """Insert parametry_analityczne(id=59) + 2 parametry_etapy rows in
    pre-migration state (grupa='lab', cert_qualitative_result='≤1,0')."""
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, grupa, precision) "
        "VALUES (59, 'cert_qual_rozklad_kwasow', 'Rozkład kwasów', 'jakosciowy', 'lab', 2)"
    )
    db.execute("INSERT OR IGNORE INTO produkty (nazwa, display_name) VALUES ('Monamid_KO', 'Monamid KO')")
    db.execute(
        "INSERT INTO parametry_etapy (id, produkt, kontekst, parametr_id, grupa, "
        "cert_qualitative_result) VALUES (472, 'Monamid_KO', 'analiza_koncowa', 59, 'lab', '≤1,0')"
    )
    db.execute(
        "INSERT INTO parametry_etapy (id, produkt, kontekst, parametr_id, grupa, "
        "cert_qualitative_result) VALUES (613, 'Monamid_KO', 'cert_variant', 59, 'lab', NULL)"
    )
    db.commit()


def test_migration_applies_all_four_changes(db):
    _seed_baseline(db)
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start) "
        "VALUES (1, 'b1', '1/26', '2026-01-01T00:00:00')"
    )
    db.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc_text, "
        "is_manual, dt_wpisu, wpisal) "
        "VALUES (1, 'analiza_koncowa', 'cert_qual_rozklad_kwasow', 'tag', '≤1,0', "
        "0, '2026-01-01T00:00:00', 'op')"
    )
    db.commit()

    counts = run_migration(db)

    rows = db.execute(
        "SELECT cert_qualitative_result FROM parametry_etapy WHERE parametr_id=59"
    ).fetchall()
    assert all(r["cert_qualitative_result"] is None for r in rows)

    pa = db.execute("SELECT grupa FROM parametry_analityczne WHERE id=59").fetchone()
    assert pa["grupa"] == "zewn"

    pe = db.execute("SELECT grupa FROM parametry_etapy WHERE parametr_id=59").fetchall()
    assert all(r["grupa"] == "zewn" for r in pe)

    n = db.execute(
        "SELECT COUNT(*) FROM ebr_wyniki WHERE kod_parametru='cert_qual_rozklad_kwasow'"
    ).fetchone()[0]
    assert n == 0

    assert counts == {"cert_qr_cleared": 1, "pa_grupa": 1, "pe_grupa": 2, "ebr_purged": 1}


def test_migration_is_idempotent(db):
    _seed_baseline(db)
    run_migration(db)
    counts = run_migration(db)
    assert counts == {"cert_qr_cleared": 0, "pa_grupa": 0, "pe_grupa": 0, "ebr_purged": 0}


def test_migration_preserves_filled_ebr_wyniki(db):
    _seed_baseline(db)
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start) "
        "VALUES (1, 'b1', '1/26', '2026-01-01T00:00:00')"
    )
    db.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc_text, "
        "is_manual, dt_wpisu, wpisal) "
        "VALUES (1, 'analiza_koncowa', 'cert_qual_rozklad_kwasow', 'tag', "
        "'<1|45|22|18|10|3|1|0|0', 1, '2026-01-01T00:00:00', 'op')"
    )
    db.commit()

    run_migration(db)

    n = db.execute(
        "SELECT COUNT(*) FROM ebr_wyniki WHERE kod_parametru='cert_qual_rozklad_kwasow'"
    ).fetchone()[0]
    assert n == 1


def test_migration_preserves_unrelated_etap_seed(db):
    _seed_baseline(db)
    db.execute(
        "UPDATE parametry_etapy SET cert_qualitative_result='custom value' WHERE id=472"
    )
    db.commit()

    run_migration(db)

    row = db.execute(
        "SELECT cert_qualitative_result FROM parametry_etapy WHERE id=472"
    ).fetchone()
    assert row["cert_qualitative_result"] == "custom value"


def test_run_migration_does_not_commit(db):
    """run_migration mutates the connection but leaves commit decision to caller.
    Caller can roll back to verify dry-run behavior end-to-end."""
    _seed_baseline(db)
    counts = run_migration(db)
    assert counts["pa_grupa"] == 1  # mutation happened in-memory
    db.rollback()
    # After rollback, original state should be restored
    pa = db.execute("SELECT grupa FROM parametry_analityczne WHERE id=59").fetchone()
    assert pa["grupa"] == "lab"  # rolled back
