"""Tests for scripts/mvp_pipeline_cleanup.py — MVP narrowing of multi-stage
pipeline to Chegina_K7 only, plus K7 typ-flag fixup."""

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


def _seed_full_pipeline_state(db):
    """Seed DB state as it looks AFTER PR 1-6 of parametry SSOT refactor:
    Chegina_K7 has 5 analytical etapy + 5 process etapy, Chegina_K40GL has
    5 analytical + 5 process, Chelamid_DK has 1 analytical + 0 process.
    All typ flags default 1/1/0."""
    db.execute("DELETE FROM parametry_analityczne")
    db.execute("DELETE FROM produkt_etapy")
    db.execute("DELETE FROM produkt_pipeline")
    db.executemany(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision, aktywny) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        [
            (1, "ph_10proc", "pH 10%", "bezposredni", 2),
            (2, "nd20", "nD20", "bezposredni", 4),
            (3, "sm", "Sucha masa", "bezposredni", 2),
            (4, "sa", "SA", "titracja", 2),
            (5, "so3", "SO3", "titracja", 2),
            (6, "nacl", "NaCl", "titracja", 2),
            (7, "barwa_I2", "Barwa I2", "bezposredni", 0),
            (8, "kwas_ca", "Kwas cytrynowy [kg]", "bezposredni", 1),
        ],
    )
    db.executemany(
        "INSERT OR IGNORE INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (?, ?, ?, ?)",
        [
            (1, "amidowanie", "Amidowanie", "cykliczny"),
            (3, "namca", "NAMCA", "cykliczny"),
            (2, "czwartorzedowanie", "Czwartorzedowanie", "cykliczny"),
            (4, "sulfonowanie", "Sulfonowanie", "cykliczny"),
            (5, "utlenienie", "Utlenienie", "cykliczny"),
            (6, "analiza_koncowa", "Analiza koncowa", "jednorazowy"),
            (7, "dodatki", "Dodatki standaryzacyjne", "cykliczny"),
            (9, "standaryzacja", "Standaryzacja", "cykliczny"),
        ],
    )
    db.execute(
        "INSERT OR IGNORE INTO etapy_procesowe (kod, label, aktywny) VALUES (?, ?, 1)",
        ("amidowanie", "Amidowanie"),
    )
    for kod in ("namca", "czwartorzedowanie", "sulfonowanie", "utlenienie", "standaryzacja"):
        db.execute(
            "INSERT OR IGNORE INTO etapy_procesowe (kod, label, aktywny) VALUES (?, ?, 1)",
            (kod, kod.capitalize()),
        )

    # ---- Chegina_K7: 5 analytical etapy + 5 process etapy ----
    k7_pipeline = [
        (4, 1),   # sulfonowanie, kolejnosc 1
        (5, 2),   # utlenienie
        (9, 3),   # standaryzacja
        (6, 4),   # analiza_koncowa
        (7, 5),   # dodatki
    ]
    for etap_id, kol in k7_pipeline:
        db.execute(
            "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chegina_K7', ?, ?)",
            (etap_id, kol),
        )
    k7_process = ["amidowanie", "namca", "czwartorzedowanie", "sulfonowanie", "utlenienie"]
    for i, kod in enumerate(k7_process, 1):
        db.execute(
            "INSERT INTO produkt_etapy (produkt, etap_kod, kolejnosc) VALUES ('Chegina_K7', ?, ?)",
            (kod, i),
        )
    k7_params = [
        (4, 5),  # sulfonowanie, so3
        (4, 1),  # sulfonowanie, ph_10proc
        (5, 5),  # utlenienie, so3
        (5, 6),  # utlenienie, nacl
        (9, 2),  # standaryzacja, nd20
        (9, 6),  # standaryzacja, nacl
        (6, 1),  # analiza_koncowa, ph_10proc
        (6, 3),  # analiza_koncowa, sm
        (6, 7),  # analiza_koncowa, barwa_I2
        (7, 8),  # dodatki, kwas_ca
    ]
    for etap_id, parametr_id in k7_params:
        db.execute(
            "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
            "dla_szarzy, dla_zbiornika, dla_platkowania) VALUES ('Chegina_K7', ?, ?, 1, 1, 0)",
            (etap_id, parametr_id),
        )

    # ---- Chegina_K40GL: 5 analytical + 5 process ----
    k40gl_pipeline = [(4, 1), (5, 2), (9, 3), (6, 4), (7, 5)]
    for etap_id, kol in k40gl_pipeline:
        db.execute(
            "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chegina_K40GL', ?, ?)",
            (etap_id, kol),
        )
    for i, kod in enumerate(k7_process, 1):
        db.execute(
            "INSERT INTO produkt_etapy (produkt, etap_kod, kolejnosc) VALUES ('Chegina_K40GL', ?, ?)",
            (kod, i),
        )
    for etap_id, parametr_id in k7_params:
        db.execute(
            "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
            "dla_szarzy, dla_zbiornika, dla_platkowania) VALUES ('Chegina_K40GL', ?, ?, 1, 1, 0)",
            (etap_id, parametr_id),
        )

    # ---- Chelamid_DK: 1 analytical (analiza_koncowa) ----
    db.execute(
        "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chelamid_DK', 6, 1)"
    )
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
        "dla_szarzy, dla_zbiornika, dla_platkowania) VALUES ('Chelamid_DK', 6, 1, 1, 1, 0)"
    )

    # Active MBR templates for postflight
    for produkt in ("Chegina_K7", "Chegina_K40GL", "Chelamid_DK"):
        db.execute(
            "INSERT INTO mbr_templates (produkt, status, dt_utworzenia) "
            "VALUES (?, 'active', datetime('now'))",
            (produkt,),
        )

    db.commit()


def test_script_importable():
    from scripts import mvp_pipeline_cleanup as mod
    assert callable(mod.migrate)
    assert callable(mod.main)
    assert callable(mod.backup)
    assert callable(mod.already_applied)
    assert mod.MIGRATION_NAME == "mvp_pipeline_cleanup_v1"
    assert mod.MVP_MULTI_STAGE == {"Chegina_K7"}


def test_migrate_marks_as_applied(db):
    from scripts.mvp_pipeline_cleanup import migrate, already_applied
    _seed_full_pipeline_state(db)
    migrate(db)
    assert already_applied(db) is True


def test_migrate_skips_when_already_applied(db, capsys):
    from scripts.mvp_pipeline_cleanup import migrate, already_applied
    _seed_full_pipeline_state(db)
    migrate(db)
    migrate(db)
    captured = capsys.readouterr()
    assert "already applied — skipping" in captured.out


def test_strip_removes_k40gl_multi_stage(db):
    from scripts.mvp_pipeline_cleanup import strip_non_k7_pipeline
    _seed_full_pipeline_state(db)
    strip_non_k7_pipeline(db)
    rows = db.execute(
        "SELECT etap_id FROM produkt_pipeline WHERE produkt='Chegina_K40GL' ORDER BY kolejnosc"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["etap_id"] == 6  # only analiza_koncowa


def test_strip_removes_k40gl_process_stages(db):
    from scripts.mvp_pipeline_cleanup import strip_non_k7_pipeline
    _seed_full_pipeline_state(db)
    strip_non_k7_pipeline(db)
    n = db.execute(
        "SELECT COUNT(*) AS n FROM produkt_etapy WHERE produkt='Chegina_K40GL'"
    ).fetchone()["n"]
    assert n == 0


def test_strip_preserves_chegina_k7(db):
    from scripts.mvp_pipeline_cleanup import strip_non_k7_pipeline
    _seed_full_pipeline_state(db)
    strip_non_k7_pipeline(db)
    n_pipeline = db.execute(
        "SELECT COUNT(*) AS n FROM produkt_pipeline WHERE produkt='Chegina_K7'"
    ).fetchone()["n"]
    n_process = db.execute(
        "SELECT COUNT(*) AS n FROM produkt_etapy WHERE produkt='Chegina_K7'"
    ).fetchone()["n"]
    assert n_pipeline == 5
    assert n_process == 5


def test_strip_preserves_already_simple_products(db):
    from scripts.mvp_pipeline_cleanup import strip_non_k7_pipeline
    _seed_full_pipeline_state(db)
    strip_non_k7_pipeline(db)
    rows = db.execute(
        "SELECT etap_id FROM produkt_pipeline WHERE produkt='Chelamid_DK'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["etap_id"] == 6


def test_strip_inserts_analiza_koncowa_if_missing(db):
    """Edge case: a product with multi-stage pipeline but no analiza_koncowa row
    should have analiza_koncowa inserted when its multi-stage entries are stripped."""
    from scripts.mvp_pipeline_cleanup import strip_non_k7_pipeline
    _seed_full_pipeline_state(db)
    # Remove K40GL's analiza_koncowa specifically
    db.execute("DELETE FROM produkt_pipeline WHERE produkt='Chegina_K40GL' AND etap_id=6")
    db.commit()
    strip_non_k7_pipeline(db)
    rows = db.execute(
        "SELECT etap_id FROM produkt_pipeline WHERE produkt='Chegina_K40GL'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["etap_id"] == 6


def test_fixup_k7_removes_dodatki_stage(db):
    from scripts.mvp_pipeline_cleanup import fixup_chegina_k7
    _seed_full_pipeline_state(db)
    fixup_chegina_k7(db)
    kody = [r["kod"] for r in db.execute(
        "SELECT ea.kod FROM produkt_pipeline pp "
        "JOIN etapy_analityczne ea ON pp.etap_id=ea.id "
        "WHERE pp.produkt='Chegina_K7' ORDER BY pp.kolejnosc"
    ).fetchall()]
    assert "dodatki" not in kody
    assert kody == ["sulfonowanie", "utlenienie", "standaryzacja", "analiza_koncowa"]


def test_fixup_k7_removes_dodatki_params(db):
    from scripts.mvp_pipeline_cleanup import fixup_chegina_k7
    _seed_full_pipeline_state(db)
    fixup_chegina_k7(db)
    n = db.execute(
        "SELECT COUNT(*) AS n FROM produkt_etap_limity WHERE produkt='Chegina_K7' AND etap_id=7"
    ).fetchone()["n"]
    assert n == 0


def test_fixup_k7_sets_szarza_flags_on_process_stages(db):
    """sulfonowanie/utlenienie/standaryzacja params → dla_szarzy=1, dla_zbiornika=0."""
    from scripts.mvp_pipeline_cleanup import fixup_chegina_k7
    _seed_full_pipeline_state(db)
    fixup_chegina_k7(db)
    rows = db.execute(
        "SELECT pel.dla_szarzy, pel.dla_zbiornika FROM produkt_etap_limity pel "
        "WHERE pel.produkt='Chegina_K7' AND pel.etap_id IN (4, 5, 9)"
    ).fetchall()
    assert len(rows) > 0
    for r in rows:
        assert r["dla_szarzy"] == 1
        assert r["dla_zbiornika"] == 0


def test_fixup_k7_sets_zbiornik_flags_on_analiza_koncowa(db):
    """analiza_koncowa params → dla_szarzy=0, dla_zbiornika=1."""
    from scripts.mvp_pipeline_cleanup import fixup_chegina_k7
    _seed_full_pipeline_state(db)
    fixup_chegina_k7(db)
    rows = db.execute(
        "SELECT dla_szarzy, dla_zbiornika FROM produkt_etap_limity "
        "WHERE produkt='Chegina_K7' AND etap_id=6"
    ).fetchall()
    assert len(rows) > 0
    for r in rows:
        assert r["dla_szarzy"] == 0
        assert r["dla_zbiornika"] == 1


def test_fixup_k7_trims_process_etapy(db):
    """produkt_etapy for K7: keep sulfonowanie, utlenienie, add standaryzacja;
    drop amidowanie, namca, czwartorzedowanie."""
    from scripts.mvp_pipeline_cleanup import fixup_chegina_k7
    _seed_full_pipeline_state(db)
    fixup_chegina_k7(db)
    kody = {r["etap_kod"] for r in db.execute(
        "SELECT etap_kod FROM produkt_etapy WHERE produkt='Chegina_K7'"
    ).fetchall()}
    assert kody == {"sulfonowanie", "utlenienie", "standaryzacja"}


def test_orphan_cleanup_removes_stranded_limity(db):
    """After strip+fixup, K40GL has orphan produkt_etap_limity rows for etap_ids
    no longer in its pipeline. Those must be deleted."""
    from scripts.mvp_pipeline_cleanup import strip_non_k7_pipeline, fixup_chegina_k7, clean_orphan_limits
    _seed_full_pipeline_state(db)
    strip_non_k7_pipeline(db)
    fixup_chegina_k7(db)
    clean_orphan_limits(db)
    rows = db.execute(
        "SELECT DISTINCT etap_id FROM produkt_etap_limity WHERE produkt='Chegina_K40GL'"
    ).fetchall()
    etap_ids = sorted(r["etap_id"] for r in rows)
    assert etap_ids == [6]


def test_orphan_cleanup_preserves_k7_limity(db):
    """K7 has pipeline for 4 etapy after fixup (dodatki dropped). Its limity
    for those 4 etapy must survive orphan cleanup."""
    from scripts.mvp_pipeline_cleanup import strip_non_k7_pipeline, fixup_chegina_k7, clean_orphan_limits
    _seed_full_pipeline_state(db)
    strip_non_k7_pipeline(db)
    fixup_chegina_k7(db)
    clean_orphan_limits(db)
    etap_ids = {r["etap_id"] for r in db.execute(
        "SELECT DISTINCT etap_id FROM produkt_etap_limity WHERE produkt='Chegina_K7'"
    ).fetchall()}
    assert etap_ids == {4, 5, 9, 6}


def test_postflight_passes_after_full_cleanup(db):
    from scripts.mvp_pipeline_cleanup import migrate, postflight
    _seed_full_pipeline_state(db)
    migrate(db)
    assert postflight(db) == []


def test_postflight_detects_active_product_without_pipeline(db):
    """If an active MBR product has 0 produkt_pipeline rows, postflight fails."""
    from scripts.mvp_pipeline_cleanup import postflight
    _seed_full_pipeline_state(db)
    db.execute("DELETE FROM produkt_pipeline WHERE produkt='Chelamid_DK'")
    db.commit()
    errors = postflight(db)
    assert any("Chelamid_DK" in e and "no pipeline" in e.lower() for e in errors)


def test_postflight_detects_non_k7_with_multi_stage_leftover(db):
    """If any non-K7 product still has multi-stage pipeline, postflight fails."""
    from scripts.mvp_pipeline_cleanup import postflight
    _seed_full_pipeline_state(db)
    errors = postflight(db)
    # Pre-cleanup state — K40GL still has 5 pipeline rows
    assert any("Chegina_K40GL" in e and "multi-stage" in e.lower() for e in errors)


def test_postflight_detects_k7_with_dodatki(db):
    """K7 pipeline must not contain dodatki etap."""
    from scripts.mvp_pipeline_cleanup import strip_non_k7_pipeline, postflight
    _seed_full_pipeline_state(db)
    strip_non_k7_pipeline(db)  # dodatki still present for K7
    errors = postflight(db)
    assert any("Chegina_K7" in e and "dodatki" in e.lower() for e in errors)


def test_full_migrate_cleans_state_correctly(db):
    """One-shot migrate() call moves seeded state to target MVP shape."""
    from scripts.mvp_pipeline_cleanup import migrate, already_applied

    _seed_full_pipeline_state(db)

    # Pre-migration sanity
    assert db.execute(
        "SELECT COUNT(*) AS n FROM produkt_pipeline WHERE produkt='Chegina_K40GL'"
    ).fetchone()["n"] == 5

    migrate(db)

    # K7: 4 pipeline rows (sulfon, utlen, standard, analiza_koncowa), no dodatki
    k7_kody = [r["kod"] for r in db.execute(
        "SELECT ea.kod FROM produkt_pipeline pp JOIN etapy_analityczne ea ON pp.etap_id=ea.id "
        "WHERE pp.produkt='Chegina_K7' ORDER BY pp.kolejnosc"
    ).fetchall()]
    assert k7_kody == ["sulfonowanie", "utlenienie", "standaryzacja", "analiza_koncowa"]

    # K7 process workflow: 3 stages
    k7_proc = {r["etap_kod"] for r in db.execute(
        "SELECT etap_kod FROM produkt_etapy WHERE produkt='Chegina_K7'"
    ).fetchall()}
    assert k7_proc == {"sulfonowanie", "utlenienie", "standaryzacja"}

    # K40GL: 1 pipeline row (analiza_koncowa), no process etapy
    k40gl = db.execute(
        "SELECT etap_id FROM produkt_pipeline WHERE produkt='Chegina_K40GL'"
    ).fetchall()
    assert len(k40gl) == 1
    assert k40gl[0]["etap_id"] == 6
    assert db.execute(
        "SELECT COUNT(*) AS n FROM produkt_etapy WHERE produkt='Chegina_K40GL'"
    ).fetchone()["n"] == 0

    # K7 typ flags: szarza stages vs analiza_koncowa
    szarza_rows = db.execute(
        "SELECT dla_szarzy, dla_zbiornika FROM produkt_etap_limity "
        "WHERE produkt='Chegina_K7' AND etap_id IN (4, 5, 9)"
    ).fetchall()
    assert all(r["dla_szarzy"] == 1 and r["dla_zbiornika"] == 0 for r in szarza_rows)
    zbiornik_rows = db.execute(
        "SELECT dla_szarzy, dla_zbiornika FROM produkt_etap_limity "
        "WHERE produkt='Chegina_K7' AND etap_id=6"
    ).fetchall()
    assert all(r["dla_szarzy"] == 0 and r["dla_zbiornika"] == 1 for r in zbiornik_rows)

    # No orphan limits
    orphans = db.execute("""
        SELECT COUNT(*) AS n FROM produkt_etap_limity pel
        WHERE (pel.produkt, pel.etap_id) NOT IN (SELECT produkt, etap_id FROM produkt_pipeline)
    """).fetchone()["n"]
    assert orphans == 0

    # Marker set
    assert already_applied(db) is True


