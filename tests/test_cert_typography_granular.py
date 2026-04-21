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
    assert settings["body_font_family"] == "Bookman Old Style"


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
    out = _apply_typography_overrides(src, font="TeX Gyre Bonum", sizes=sizes)

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
    out = _apply_typography_overrides(src, font="Bookman Old Style", sizes=sizes)
    assert _read_docx_part(out, "word/document.xml") == doc
