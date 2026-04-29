"""Granular cert typography: migration + _load_cert_settings + overrides."""

import sqlite3
from io import BytesIO
from zipfile import ZipFile

import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _get_setting(db, key):
    row = db.execute("SELECT value FROM cert_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def test_migration_seeds_three_new_keys_on_fresh_db(db):
    assert _get_setting(db, "title_font_size_pt") == "12"
    assert _get_setting(db, "product_name_font_size_pt") == "16"
    assert _get_setting(db, "body_font_size_pt") == "11"


def test_migration_copies_legacy_header_font_size_pt_into_title_and_product():
    """Existing prod DB with only header_font_size_pt=12 (and no title/product
    keys) must end up with title=12 and product=12 after migration — no
    visual regression for users who had the old setting in place."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Simulate "legacy DB" — seed cert_settings with only the old key first.
    conn.execute("""
        CREATE TABLE cert_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)
    """)
    conn.execute("INSERT INTO cert_settings (key, value) VALUES ('header_font_size_pt', '12')")
    conn.commit()
    # Now run init_mbr_tables — migration should pick up the existing value.
    init_mbr_tables(conn)
    rows = dict(conn.execute("SELECT key, value FROM cert_settings").fetchall())
    assert rows["title_font_size_pt"] == "12"
    assert rows["product_name_font_size_pt"] == "12"
    assert rows["body_font_size_pt"] == "11"
    conn.close()


def test_migration_is_idempotent():
    """Running init_mbr_tables twice leaves cert_settings unchanged."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    # Tweak a value between runs — migration must NOT clobber it.
    conn.execute(
        "UPDATE cert_settings SET value=? WHERE key=?", ("22", "title_font_size_pt")
    )
    conn.commit()
    init_mbr_tables(conn)
    row = conn.execute(
        "SELECT value FROM cert_settings WHERE key='title_font_size_pt'"
    ).fetchone()
    assert row["value"] == "22"
    conn.close()


def test_load_cert_settings_returns_three_new_size_keys(db):
    from mbr.certs.generator import _load_cert_settings
    settings = _load_cert_settings(db)
    assert settings["title_font_size_pt"] == 12
    assert settings["product_name_font_size_pt"] == 16
    assert settings["body_font_size_pt"] == 11
    assert settings["body_font_family"] == "Noto Serif"


def test_load_cert_settings_returns_header_font_family(db):
    """New: header_font_family lives next to body_font_family in cert_settings."""
    from mbr.certs.generator import _load_cert_settings
    settings = _load_cert_settings(db)
    assert settings["header_font_family"] == "Noto Sans"


def test_migration_seeds_header_font_family_on_fresh_db(db):
    """Fresh DB → header_font_family default is 'Noto Sans' (sans-serif pair)."""
    assert _get_setting(db, "header_font_family") == "Noto Sans"


def test_migration_copies_existing_body_font_to_header_on_upgrade():
    """Admin-customized body_font_family must be copied to header_font_family
    on upgrade — preserves visual until admin explicitly changes header."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Simulate legacy DB: only body_font_family is set, with a CUSTOM value.
    conn.execute("CREATE TABLE cert_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO cert_settings (key, value) VALUES ('body_font_family', 'EB Garamond')")
    conn.commit()
    init_mbr_tables(conn)
    rows = dict(conn.execute("SELECT key, value FROM cert_settings").fetchall())
    # body untouched (custom value preserved)
    assert rows["body_font_family"] == "EB Garamond"
    # header copied from custom body — same font, no surprise typographic mismatch
    assert rows["header_font_family"] == "EB Garamond"
    conn.close()


def test_migration_replaces_deprecated_default_with_noto_serif():
    """'Source Serif 4' was a previous default but isn't shipped in our
    Gotenberg image (silent fallback). Migration normalizes it to Noto Serif
    (which IS bundled). 'Bookman Old Style' / 'TeX Gyre Bonum' likewise."""
    for legacy in ("Source Serif 4", "Bookman Old Style", "TeX Gyre Bonum"):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE cert_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO cert_settings (key, value) VALUES ('body_font_family', ?)",
            (legacy,),
        )
        conn.commit()
        init_mbr_tables(conn)
        body = conn.execute(
            "SELECT value FROM cert_settings WHERE key='body_font_family'"
        ).fetchone()["value"]
        header = conn.execute(
            "SELECT value FROM cert_settings WHERE key='header_font_family'"
        ).fetchone()["value"]
        # Body normalized to Noto Serif; header gets the fresh-install sans default
        # (since the deprecated value isn't a meaningful customization to preserve).
        assert body == "Noto Serif", f"body migration for {legacy} produced {body}"
        assert header == "Noto Sans", f"header default for {legacy} produced {header}"
        conn.close()


def _make_docx_bytes(xml_parts: dict) -> bytes:
    buf = BytesIO()
    with ZipFile(buf, "w") as zf:
        for name, xml in xml_parts.items():
            zf.writestr(name, xml)
    return buf.getvalue()


def _read_docx_part(docx_bytes: bytes, name: str) -> str:
    with ZipFile(BytesIO(docx_bytes), "r") as zf:
        return zf.read(name).decode("utf-8")


def test_overrides_substitute_three_sentinels_and_body_22():
    """_apply_typography_overrides must rewrite 996/997 in header and styles,
    and 22 in document.xml, each to value*2 (half-points)."""
    from mbr.certs.generator import _apply_typography_overrides

    header_xml = (
        '<?xml version="1.0"?><w:hdr xmlns:w="x">'
        '<w:p><w:r><w:rPr><w:szCs w:val="996"/></w:rPr><w:t>TITLE</w:t></w:r></w:p>'
        '<w:p><w:r><w:rPr><w:szCs w:val="997"/></w:rPr><w:t>{{display_name}}</w:t></w:r></w:p>'
        '</w:hdr>'
    )
    styles_xml = (
        '<?xml version="1.0"?><w:styles xmlns:w="x">'
        '<w:style w:styleId="Nagwek4"><w:rPr><w:sz w:val="996"/></w:rPr></w:style>'
        '<w:style w:styleId="Nagwek8"><w:rPr><w:sz w:val="997"/></w:rPr></w:style>'
        '</w:styles>'
    )
    document_xml = (
        '<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
        '<w:p><w:r><w:rPr><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr><w:t>Body</w:t></w:r></w:p>'
        '<w:p><w:r><w:rPr><w:sz w:val="2"/></w:rPr><w:t>spacer</w:t></w:r></w:p>'
        '</w:body></w:document>'
    )
    src = _make_docx_bytes({
        "word/header1.xml":  header_xml,
        "word/styles.xml":   styles_xml,
        "word/document.xml": document_xml,
    })

    sizes = {"title_pt": 14, "product_name_pt": 20, "body_pt": 9}
    out = _apply_typography_overrides(
        src, body_font="TeX Gyre Bonum", header_font="Bookman Old Style", sizes=sizes
    )

    out_header = _read_docx_part(out, "word/header1.xml")
    assert 'w:szCs w:val="28"' in out_header       # 14pt title * 2
    assert 'w:szCs w:val="40"' in out_header       # 20pt product * 2
    assert '996' not in out_header
    assert '997' not in out_header

    out_styles = _read_docx_part(out, "word/styles.xml")
    assert 'w:sz w:val="28"' in out_styles         # Nagwek4 → title
    assert 'w:sz w:val="40"' in out_styles         # Nagwek8 → product name
    assert '996' not in out_styles
    assert '997' not in out_styles

    out_doc = _read_docx_part(out, "word/document.xml")
    assert 'w:sz w:val="18"' in out_doc            # 9pt body * 2
    assert 'w:szCs w:val="18"' in out_doc
    assert 'w:sz w:val="22"' not in out_doc
    assert 'w:sz w:val="2"' in out_doc             # 1-pt spacer UNTOUCHED
    assert '<w:t>spacer</w:t>' in out_doc


def test_overrides_do_not_touch_body_when_body_pt_equals_11():
    """Default body_pt=11 means new_val=22 (same as sentinel); bytes identical."""
    from mbr.certs.generator import _apply_typography_overrides

    doc = (
        '<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
        '<w:p><w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t>x</w:t></w:r></w:p>'
        '</w:body></w:document>'
    )
    src = _make_docx_bytes({
        "word/header1.xml":  '<?xml version="1.0"?><w:hdr xmlns:w="x"/>',
        "word/styles.xml":   '<?xml version="1.0"?><w:styles xmlns:w="x"/>',
        "word/document.xml": doc,
    })
    sizes = {"title_pt": 12, "product_name_pt": 16, "body_pt": 11}
    out = _apply_typography_overrides(
        src, body_font="TeX Gyre Bonum", header_font="Bookman Old Style", sizes=sizes
    )
    # Both fonts match the in-template literals → no font rewrite should occur,
    # AND body_pt=11 → no size rewrite. Bytes therefore unchanged.
    assert _read_docx_part(out, "word/document.xml") == doc


def test_overrides_apply_body_and_header_fonts_independently():
    """body_font replaces ONLY in word/document.xml; header_font replaces ONLY
    in word/header1.xml. Cross-talk (header font leaking into document, body
    font leaking into header) is the regression we're guarding against."""
    from mbr.certs.generator import _apply_typography_overrides

    header_xml = (
        '<?xml version="1.0"?><w:hdr xmlns:w="x">'
        '<w:p><w:r><w:rPr>'
        '<w:rFonts w:ascii="Bookman Old Style" w:hAnsi="Bookman Old Style"/>'
        '<w:szCs w:val="996"/>'
        '</w:rPr><w:t>TITLE</w:t></w:r></w:p>'
        '</w:hdr>'
    )
    document_xml = (
        '<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
        '<w:p><w:r><w:rPr>'
        '<w:rFonts w:ascii="TeX Gyre Bonum" w:hAnsi="TeX Gyre Bonum"/>'
        '<w:sz w:val="22"/>'
        '</w:rPr><w:t>Body</w:t></w:r></w:p>'
        '</w:body></w:document>'
    )
    src = _make_docx_bytes({
        "word/header1.xml":  header_xml,
        "word/styles.xml":   '<?xml version="1.0"?><w:styles xmlns:w="x"/>',
        "word/document.xml": document_xml,
    })

    sizes = {"title_pt": 12, "product_name_pt": 16, "body_pt": 11}
    out = _apply_typography_overrides(
        src, body_font="Noto Serif", header_font="Noto Sans", sizes=sizes
    )

    out_doc = _read_docx_part(out, "word/document.xml")
    assert 'w:ascii="Noto Serif"' in out_doc
    assert 'w:hAnsi="Noto Serif"' in out_doc
    # Header font must NOT appear in document.xml (no cross-talk)
    assert "Noto Sans" not in out_doc
    assert "TeX Gyre Bonum" not in out_doc

    out_hdr = _read_docx_part(out, "word/header1.xml")
    assert 'w:ascii="Noto Sans"' in out_hdr
    assert 'w:hAnsi="Noto Sans"' in out_hdr
    # Body font must NOT appear in header1.xml
    assert "Noto Serif" not in out_hdr
    assert "Bookman Old Style" not in out_hdr


def test_overrides_substitute_styles_xml_latin_default_fonts():
    """word/styles.xml typically references "Times New Roman" (default serif)
    and "Arial" (default sans) in <w:rFonts> for paragraph/character styles.
    Without substitution these would render as LiberationSerif/Sans fallback in
    Gotenberg (Times New Roman is proprietary, not in the image), clashing
    with Noto used elsewhere. Replace Times New Roman → body_font, Arial →
    header_font. Leave non-Latin script fonts (cs/eastAsia) and language
    attributes untouched."""
    from mbr.certs.generator import _apply_typography_overrides

    styles_xml = (
        '<?xml version="1.0"?><w:styles xmlns:w="x">'
        '<w:docDefaults><w:rPrDefault><w:rPr>'
        '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" '
        'w:cs="Mangal" w:eastAsia="SimSun"/>'
        '<w:lang w:val="pl-PL" w:eastAsia="zh-CN"/>'
        '</w:rPr></w:rPrDefault></w:docDefaults>'
        '<w:style w:styleId="Heading1"><w:rPr>'
        '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Tahoma"/>'
        '</w:rPr></w:style>'
        '</w:styles>'
    )
    src = _make_docx_bytes({
        "word/header1.xml":  '<?xml version="1.0"?><w:hdr xmlns:w="x"/>',
        "word/styles.xml":   styles_xml,
        "word/document.xml": '<?xml version="1.0"?><w:document xmlns:w="x"><w:body/></w:document>',
    })

    sizes = {"title_pt": 12, "product_name_pt": 16, "body_pt": 11}
    out = _apply_typography_overrides(
        src, body_font="Noto Serif", header_font="Noto Sans", sizes=sizes
    )
    out_styles = _read_docx_part(out, "word/styles.xml")

    # Times New Roman → Noto Serif (body)
    assert 'w:ascii="Noto Serif"' in out_styles
    assert 'w:hAnsi="Noto Serif"' in out_styles
    assert "Times New Roman" not in out_styles

    # Arial → Noto Sans (header)
    assert 'w:ascii="Noto Sans"' in out_styles
    assert 'w:hAnsi="Noto Sans"' in out_styles
    assert "Arial" not in out_styles

    # Non-Latin script fallbacks UNTOUCHED
    assert 'w:cs="Mangal"' in out_styles
    assert 'w:eastAsia="SimSun"' in out_styles
    assert 'w:cs="Tahoma"' in out_styles

    # Language attributes UNTOUCHED (regex scoped to font values, not w:lang)
    assert 'w:val="pl-PL"' in out_styles
    assert 'w:eastAsia="zh-CN"' in out_styles


def test_overrides_styles_xml_no_order_corruption_when_body_is_arial():
    """If admin sets body_font='Arial' and header_font='Times New Roman',
    naive sequential substitution (header first then body) would clobber the
    just-replaced 'Times New Roman' in the second pass. Single-pass mapping
    must keep them independent."""
    from mbr.certs.generator import _apply_typography_overrides

    styles_xml = (
        '<?xml version="1.0"?><w:styles xmlns:w="x">'
        '<w:style w:styleId="A"><w:rPr><w:rFonts w:ascii="Times New Roman"/></w:rPr></w:style>'
        '<w:style w:styleId="B"><w:rPr><w:rFonts w:ascii="Arial"/></w:rPr></w:style>'
        '</w:styles>'
    )
    src = _make_docx_bytes({
        "word/header1.xml":  '<?xml version="1.0"?><w:hdr xmlns:w="x"/>',
        "word/styles.xml":   styles_xml,
        "word/document.xml": '<?xml version="1.0"?><w:document xmlns:w="x"><w:body/></w:document>',
    })

    sizes = {"title_pt": 12, "product_name_pt": 16, "body_pt": 11}
    out = _apply_typography_overrides(
        src, body_font="Arial", header_font="Times New Roman", sizes=sizes
    )
    out_styles = _read_docx_part(out, "word/styles.xml")

    # Each source font maps to exactly one target — no chained substitution.
    # styleId="A" was Times New Roman → body_font="Arial"
    # styleId="B" was Arial          → header_font="Times New Roman"
    assert out_styles.count('w:ascii="Arial"') == 1
    assert out_styles.count('w:ascii="Times New Roman"') == 1


from contextlib import contextmanager


@pytest.fixture
def client(monkeypatch, db):
    import mbr.db
    import mbr.certs.routes
    from mbr.app import app

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.certs.routes, "db_session", fake_db_session)
    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["user"] = {"username": "admin_test", "login": "admin_test", "rola": "admin", "id": 1}
        yield c


def test_get_cert_settings_returns_three_new_keys(client):
    r = client.get("/api/cert/settings")
    assert r.status_code == 200
    d = r.get_json()
    assert d["title_font_size_pt"] == 12
    assert d["product_name_font_size_pt"] == 16
    assert d["body_font_size_pt"] == 11


def test_put_cert_settings_accepts_three_new_keys(client, db):
    r = client.put("/api/cert/settings", json={
        "title_font_size_pt": 14,
        "product_name_font_size_pt": 18,
        "body_font_size_pt": 10,
    })
    assert r.status_code == 200, r.get_json()
    assert _get_setting(db, "title_font_size_pt") == "14"
    assert _get_setting(db, "product_name_font_size_pt") == "18"
    assert _get_setting(db, "body_font_size_pt") == "10"


def test_put_cert_settings_validates_range(client):
    r = client.put("/api/cert/settings", json={"title_font_size_pt": 100})
    assert r.status_code == 400
    r = client.put("/api/cert/settings", json={"body_font_size_pt": 0})
    assert r.status_code == 400


def test_get_cert_settings_returns_header_font_family(client):
    r = client.get("/api/cert/settings")
    assert r.status_code == 200
    d = r.get_json()
    assert d["header_font_family"] == "Noto Sans"


def test_put_cert_settings_accepts_header_font_family(client, db):
    r = client.put("/api/cert/settings", json={"header_font_family": "Lato"})
    assert r.status_code == 200, r.get_json()
    assert _get_setting(db, "header_font_family") == "Lato"


def test_put_cert_settings_rejects_empty_header_font_family(client):
    r = client.put("/api/cert/settings", json={"header_font_family": "   "})
    assert r.status_code == 400


def test_put_cert_settings_rejects_xml_unsafe_header_font(client):
    r = client.put("/api/cert/settings", json={"header_font_family": 'Bad"font'})
    assert r.status_code == 400


def test_put_cert_settings_silently_ignores_legacy_header_font_size_pt(client, db):
    """Legacy key must NOT 400; it's dropped from the whitelist. At least one
    valid key must be present for the request to succeed overall."""
    r = client.put("/api/cert/settings", json={
        "header_font_size_pt": 14,  # legacy — ignored
        "title_font_size_pt": 13,   # valid — applied
    })
    assert r.status_code == 200
    assert _get_setting(db, "title_font_size_pt") == "13"
    # Legacy value is NOT written by this endpoint — it remains at its prior
    # (migration-seeded) value.
    # Default seed is "14" (from _cert_settings_defaults); the put should not
    # overwrite it with the ignored request body.
    assert _get_setting(db, "header_font_size_pt") == "14"
