"""Cert flexibility — schema migrations + helpers + endpoints."""

import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


# ===========================================================================
# Task 1: schema migrations
# ===========================================================================

def test_schema_swiadectwa_has_recipient_name(db):
    cols = {r["name"] for r in db.execute("PRAGMA table_info(swiadectwa)").fetchall()}
    assert "recipient_name" in cols


def test_schema_swiadectwa_has_expiry_months_used(db):
    cols = {r["name"] for r in db.execute("PRAGMA table_info(swiadectwa)").fetchall()}
    assert "expiry_months_used" in cols


def test_schema_cert_variants_has_archived(db):
    cols = {r["name"] for r in db.execute("PRAGMA table_info(cert_variants)").fetchall()}
    assert "archived" in cols


def test_schema_cert_variants_archived_default_zero(db):
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label) VALUES (?, ?, ?)",
        ("TestProd", "base", "TestProd"),
    )
    db.commit()
    row = db.execute("SELECT archived FROM cert_variants WHERE produkt='TestProd'").fetchone()
    assert row["archived"] == 0


# ===========================================================================
# Task 3: _sanitize_filename_segment
# ===========================================================================

def test_sanitize_passes_normal_text():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("ADAM&PARTNER") == "ADAM&PARTNER"


def test_sanitize_strips_path_separators():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("ADAM/PARTNER") == "ADAMPARTNER"
    assert _sanitize_filename_segment("ADAM\\PARTNER") == "ADAMPARTNER"
    assert _sanitize_filename_segment("ADAM:PARTNER") == "ADAMPARTNER"


def test_sanitize_strips_control_chars():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("ADAM\x00\x01PARTNER") == "ADAMPARTNER"


def test_sanitize_trims_whitespace():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("  ADAM  ") == "ADAM"


def test_sanitize_max_40_chars():
    from mbr.certs.generator import _sanitize_filename_segment
    long_name = "A" * 100
    assert _sanitize_filename_segment(long_name) == "A" * 40


def test_sanitize_empty_returns_empty():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("") == ""
    assert _sanitize_filename_segment("   ") == ""
    assert _sanitize_filename_segment(None) == ""


def test_sanitize_keeps_polish_chars_and_ampersand():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("Łódź & Co.") == "Łódź & Co."


# ===========================================================================
# Task 4: _cert_names with recipient + has_order_number
# ===========================================================================

def test_cert_names_baseline_unchanged():
    """Old signature still works (legacy callers)."""
    from mbr.certs.generator import _cert_names
    folder, pdf, nr = _cert_names("Chegina_K7", "Chegina K7", "4/2026")
    assert folder == "Chegina K7"
    assert pdf == "Chegina K7 4.pdf"
    assert nr == "4"


def test_cert_names_with_recipient():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7", "4/2026",
                            recipient_name="ADAM&PARTNER")
    assert pdf == "Chegina K7 — ADAM&PARTNER 4.pdf"


def test_cert_names_with_recipient_and_mb_variant():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7 — MB", "4/2026",
                            recipient_name="ADAM&PARTNER")
    assert pdf == "Chegina K7 MB — ADAM&PARTNER 4.pdf"


def test_cert_names_recipient_with_slash_sanitized():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7", "4/2026",
                            recipient_name="ADAM/Partner")
    assert pdf == "Chegina K7 — ADAMPartner 4.pdf"


def test_cert_names_empty_recipient_omitted():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7", "4/2026", recipient_name="   ")
    assert pdf == "Chegina K7 4.pdf"


def test_cert_names_with_order_number_suffix():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7", "4/2026",
                            has_order_number=True)
    assert pdf == "Chegina K7 4 (NRZAM).pdf"


def test_cert_names_with_recipient_and_order_number():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7", "4/2026",
                            recipient_name="ADAM", has_order_number=True)
    assert pdf == "Chegina K7 — ADAM 4 (NRZAM).pdf"


# ===========================================================================
# Task 5: save_certificate_pdf collision-aware + new params
# ===========================================================================

def test_save_pdf_first_call_no_suffix(tmp_path):
    from mbr.certs.generator import save_certificate_pdf
    path = save_certificate_pdf(
        b"PDF1", "Chegina_K7", "Chegina K7", "4/2026",
        output_dir=str(tmp_path),
    )
    from pathlib import Path
    p = Path(path)
    assert p.name == "Chegina K7 4.pdf"
    assert p.read_bytes() == b"PDF1"


def test_save_pdf_collision_appends_suffix(tmp_path):
    from mbr.certs.generator import save_certificate_pdf
    p1 = save_certificate_pdf(b"PDF1", "Chegina_K7", "Chegina K7", "4/2026",
                              output_dir=str(tmp_path))
    p2 = save_certificate_pdf(b"PDF2", "Chegina_K7", "Chegina K7", "4/2026",
                              output_dir=str(tmp_path))
    p3 = save_certificate_pdf(b"PDF3", "Chegina_K7", "Chegina K7", "4/2026",
                              output_dir=str(tmp_path))
    from pathlib import Path
    assert Path(p1).name == "Chegina K7 4.pdf"
    assert Path(p2).name == "Chegina K7 4 (2).pdf"
    assert Path(p3).name == "Chegina K7 4 (3).pdf"
    # Original is preserved.
    assert Path(p1).read_bytes() == b"PDF1"
    assert Path(p2).read_bytes() == b"PDF2"


def test_save_pdf_with_recipient_in_filename(tmp_path):
    from mbr.certs.generator import save_certificate_pdf
    path = save_certificate_pdf(
        b"PDF", "Chegina_K7", "Chegina K7", "4/2026",
        output_dir=str(tmp_path), recipient_name="ADAM&PARTNER",
    )
    from pathlib import Path
    assert Path(path).name == "Chegina K7 — ADAM&PARTNER 4.pdf"


def test_save_pdf_with_order_number_suffix(tmp_path):
    from mbr.certs.generator import save_certificate_pdf
    path = save_certificate_pdf(
        b"PDF", "Chegina_K7", "Chegina K7", "4/2026",
        output_dir=str(tmp_path), has_order_number=True,
    )
    from pathlib import Path
    assert Path(path).name == "Chegina K7 4 (NRZAM).pdf"


# ===========================================================================
# Task 6: save_certificate_data collision + new params
# ===========================================================================

def test_save_data_with_recipient_filename(tmp_path, monkeypatch):
    from mbr.certs import generator
    monkeypatch.setattr(generator, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(generator, "_PROJECT_ROOT", tmp_path)
    path = generator.save_certificate_data(
        "Chegina_K7", "Chegina K7", "4/2026",
        {"foo": "bar"},
        recipient_name="ADAM",
    )
    from pathlib import Path
    assert Path(path).name == "Chegina K7 — ADAM 4.json"


def test_save_data_collision_appends_suffix(tmp_path, monkeypatch):
    from mbr.certs import generator
    monkeypatch.setattr(generator, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(generator, "_PROJECT_ROOT", tmp_path)
    p1 = generator.save_certificate_data("Chegina_K7", "Chegina K7", "4/2026",
                                         {"id": 1})
    p2 = generator.save_certificate_data("Chegina_K7", "Chegina K7", "4/2026",
                                         {"id": 2})
    from pathlib import Path
    assert Path(p1).name == "Chegina K7 4.json"
    assert Path(p2).name == "Chegina K7 4 (2).json"


# ===========================================================================
# Task 7: build_context expiry_months override
# ===========================================================================

def _seed_minimal_product(db, key="TestProd", expiry_months=12):
    """Insert minimal data for build_context to succeed."""
    db.execute(
        "INSERT INTO produkty (nazwa, display_name, expiry_months) VALUES (?, ?, ?)",
        (key, key, expiry_months),
    )
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label) VALUES (?, ?, ?)",
        (key, "base", key),
    )
    db.commit()


def test_build_context_default_expiry_from_product(db, monkeypatch):
    import mbr.certs.generator as gen
    @contextmanager
    def fake_db_session():
        yield db
    monkeypatch.setattr("mbr.db.db_session", fake_db_session)
    _seed_minimal_product(db, expiry_months=12)
    from datetime import date
    ctx = gen.build_context("TestProd", "base", "1/2026", date(2026, 1, 1),
                            wyniki_flat={}, extra_fields={})
    assert ctx["dt_waznosci"] == "01.01.2027"  # +12mc


def test_build_context_override_expiry_24mc(db, monkeypatch):
    import mbr.certs.generator as gen
    @contextmanager
    def fake_db_session():
        yield db
    monkeypatch.setattr("mbr.db.db_session", fake_db_session)
    _seed_minimal_product(db, expiry_months=12)
    from datetime import date
    ctx = gen.build_context("TestProd", "base", "1/2026", date(2026, 1, 1),
                            wyniki_flat={}, extra_fields={"expiry_months": 24})
    assert ctx["dt_waznosci"] == "01.01.2028"  # +24mc


def test_build_context_override_zero_raises(db, monkeypatch):
    import mbr.certs.generator as gen
    @contextmanager
    def fake_db_session():
        yield db
    monkeypatch.setattr("mbr.db.db_session", fake_db_session)
    _seed_minimal_product(db)
    from datetime import date
    with pytest.raises(ValueError, match="out of range"):
        gen.build_context("TestProd", "base", "1/2026", date(2026, 1, 1),
                          wyniki_flat={}, extra_fields={"expiry_months": 0})


def test_build_context_override_too_high_raises(db, monkeypatch):
    import mbr.certs.generator as gen
    @contextmanager
    def fake_db_session():
        yield db
    monkeypatch.setattr("mbr.db.db_session", fake_db_session)
    _seed_minimal_product(db)
    from datetime import date
    with pytest.raises(ValueError, match="out of range"):
        gen.build_context("TestProd", "base", "1/2026", date(2026, 1, 1),
                          wyniki_flat={}, extra_fields={"expiry_months": 31})


def test_build_context_override_non_numeric_raises(db, monkeypatch):
    import mbr.certs.generator as gen
    @contextmanager
    def fake_db_session():
        yield db
    monkeypatch.setattr("mbr.db.db_session", fake_db_session)
    _seed_minimal_product(db)
    from datetime import date
    with pytest.raises(ValueError, match="Invalid expiry_months"):
        gen.build_context("TestProd", "base", "1/2026", date(2026, 1, 1),
                          wyniki_flat={}, extra_fields={"expiry_months": "abc"})


# ===========================================================================
# Task 8: create_swiadectwo persists recipient_name + expiry_months_used
# ===========================================================================

def _seed_ebr(db, produkt="TestProd", nr_partii="1/2026"):
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, dt_utworzenia) "
        "VALUES (?, 1, 'active', '[]', '{}', datetime('now'))",
        (produkt,),
    )
    mbr_id = db.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status) "
        "VALUES (?, 'B001', ?, datetime('now'), 'completed')",
        (mbr_id, nr_partii),
    )
    return db.execute("SELECT last_insert_rowid() id").fetchone()["id"]


def test_create_swiadectwo_with_recipient_and_expiry(db):
    from mbr.certs.models import create_swiadectwo
    ebr_id = _seed_ebr(db)
    cert_id = create_swiadectwo(
        db, ebr_id, "TestProd", "1/2026", "/tmp/x.pdf", "tester",
        data_json="{}", recipient_name="ADAM&PARTNER", expiry_months_used=18,
    )
    db.commit()
    row = db.execute(
        "SELECT recipient_name, expiry_months_used FROM swiadectwa WHERE id=?",
        (cert_id,),
    ).fetchone()
    assert row["recipient_name"] == "ADAM&PARTNER"
    assert row["expiry_months_used"] == 18


def test_create_swiadectwo_without_new_fields_legacy(db):
    """Legacy callers without new kwargs still work (NULL columns)."""
    from mbr.certs.models import create_swiadectwo
    ebr_id = _seed_ebr(db)
    cert_id = create_swiadectwo(
        db, ebr_id, "TestProd", "1/2026", "/tmp/x.pdf", "tester",
        data_json="{}",
    )
    db.commit()
    row = db.execute(
        "SELECT recipient_name, expiry_months_used FROM swiadectwa WHERE id=?",
        (cert_id,),
    ).fetchone()
    assert row["recipient_name"] is None
    assert row["expiry_months_used"] is None


# ===========================================================================
# Task 9: GET /api/cert/recipient-suggestions
# ===========================================================================

def _make_client(monkeypatch, db, rola="lab"):
    """Test client with fake db_session and pre-set session user."""
    import mbr.db
    import mbr.certs.routes
    @contextmanager
    def fake_db_session():
        yield db
    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.certs.routes, "db_session", fake_db_session)
    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": rola, "worker_id": None}
    return c


def _seed_swiadectwa_recipients(db, recipients):
    """Create one cert row per recipient name (or NULL)."""
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, dt_utworzenia) "
        "VALUES ('TestProd', 1, 'active', '[]', '{}', datetime('now'))"
    )
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status) "
        "VALUES (1, 'B001', '1/2026', datetime('now'), 'completed')"
    )
    for r in recipients:
        db.execute(
            "INSERT INTO swiadectwa (ebr_id, template_name, nr_partii, pdf_path, "
            "dt_wystawienia, wystawil, recipient_name) "
            "VALUES (1, 'base', '1/2026', '/x.pdf', datetime('now'), 't', ?)",
            (r,),
        )
    db.commit()


def test_recipient_suggestions_below_threshold(monkeypatch, db):
    c = _make_client(monkeypatch, db)
    _seed_swiadectwa_recipients(db, ["ADAM&PARTNER", "ADAM Partner"])
    r = c.get("/api/cert/recipient-suggestions?q=A")
    assert r.status_code == 200
    assert r.get_json() == {"suggestions": []}


def test_recipient_suggestions_returns_distinct_matches(monkeypatch, db):
    c = _make_client(monkeypatch, db)
    _seed_swiadectwa_recipients(db, [
        "ADAM&PARTNER", "ADAM&PARTNER", "ADAM Partner", "Loreal",
    ])
    r = c.get("/api/cert/recipient-suggestions?q=ad")
    out = r.get_json()["suggestions"]
    assert sorted(out) == ["ADAM Partner", "ADAM&PARTNER"]


def test_recipient_suggestions_no_match(monkeypatch, db):
    c = _make_client(monkeypatch, db)
    _seed_swiadectwa_recipients(db, ["ADAM&PARTNER"])
    r = c.get("/api/cert/recipient-suggestions?q=xyz")
    assert r.get_json() == {"suggestions": []}


def test_recipient_suggestions_excludes_null(monkeypatch, db):
    c = _make_client(monkeypatch, db)
    _seed_swiadectwa_recipients(db, ["ADAM&PARTNER", None, None])
    r = c.get("/api/cert/recipient-suggestions?q=ad")
    assert r.get_json()["suggestions"] == ["ADAM&PARTNER"]


# ===========================================================================
# Task 10: api_cert_templates default_expiry_months + include_archived
# ===========================================================================

def _seed_product_with_variants(db, produkt="TestProd", expiry_months=12,
                                 variants=(("base", "TestProd", 0),
                                          ("mb", "TestProd MB", 0))):
    """Variants: tuples of (variant_id, label, archived)."""
    db.execute(
        "INSERT INTO produkty (nazwa, display_name, expiry_months) VALUES (?, ?, ?)",
        (produkt, produkt, expiry_months),
    )
    for vid, label, arch in variants:
        db.execute(
            "INSERT INTO cert_variants (produkt, variant_id, label, archived) "
            "VALUES (?, ?, ?, ?)",
            (produkt, vid, label, arch),
        )
    db.commit()


def test_templates_returns_default_expiry_months(monkeypatch, db):
    c = _make_client(monkeypatch, db)
    _seed_product_with_variants(db, expiry_months=18)
    r = c.get("/api/cert/templates?produkt=TestProd")
    out = r.get_json()["templates"]
    assert all(t["default_expiry_months"] == 18 for t in out)


def test_templates_default_expiry_fallback_when_null(monkeypatch, db):
    c = _make_client(monkeypatch, db)
    db.execute("INSERT INTO produkty (nazwa, display_name, expiry_months) VALUES ('X', 'X', NULL)")
    db.execute("INSERT INTO cert_variants (produkt, variant_id, label) VALUES ('X', 'base', 'X')")
    db.commit()
    r = c.get("/api/cert/templates?produkt=X")
    assert r.get_json()["templates"][0]["default_expiry_months"] == 12


def test_templates_filters_archived_by_default(monkeypatch, db):
    c = _make_client(monkeypatch, db)
    _seed_product_with_variants(db, variants=(
        ("base", "TestProd", 0),
        ("legacy", "TestProd — LEGACY", 1),  # archived
    ))
    r = c.get("/api/cert/templates?produkt=TestProd")
    ids = [t["filename"] for t in r.get_json()["templates"]]
    assert "base" in ids
    assert "legacy" not in ids


def test_templates_include_archived_param(monkeypatch, db):
    c = _make_client(monkeypatch, db)
    _seed_product_with_variants(db, variants=(
        ("base", "TestProd", 0),
        ("legacy", "TestProd — LEGACY", 1),
    ))
    r = c.get("/api/cert/templates?produkt=TestProd&include_archived=1")
    ids = [t["filename"] for t in r.get_json()["templates"]]
    assert "base" in ids
    assert "legacy" in ids
