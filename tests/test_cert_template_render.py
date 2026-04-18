"""Smoke test — DOCX renders with current cert_settings and placeholders resolve."""
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


def test_docx_template_renders_without_errors(db, monkeypatch):
    """With default settings, rendering must not raise and produce bytes."""
    from mbr.certs.generator import build_preview_context, _docxtpl_render
    product = {
        "display_name": "Test Product",
        "spec_number": "P123",
        "cas_number": "",
        "expiry_months": 12,
        "opinion_pl": "OK",
        "opinion_en": "OK",
        "parameters": [
            {"id": "ph", "name_pl": "pH", "name_en": "pH", "requirement": "5-7",
             "method": "PN-EN 123", "data_field": "ph", "format": "2"},
        ],
        "variants": [{"id": "base", "label": "Test Product", "flags": [], "overrides": {}}],
    }
    ctx = build_preview_context(product, "base")
    assert "body_font_family" in ctx
    assert "header_font_size_pt" in ctx
    docx_bytes = _docxtpl_render(ctx)
    assert isinstance(docx_bytes, bytes) and len(docx_bytes) > 1000


def test_docx_geometry_changed(db):
    """After T4 DOCX edit, the document.xml has post-widening column and margin values."""
    import zipfile
    from mbr.certs.generator import _TEMPLATE_PATH
    with zipfile.ZipFile(_TEMPLATE_PATH, "r") as z:
        xml = z.read("word/document.xml").decode("utf-8")
    # Geometry changes
    assert 'w:right="737"' in xml, "margin right not updated"
    assert 'w:left="737"' in xml, "margin left not updated"
    assert 'w:w="10432"' in xml, "tblW not updated"
    assert 'w:w="5330"' in xml, "name column not widened"
    assert 'w:w="991"' in xml, "method column not narrowed"
    # Old values should be absent
    assert 'w:w="4471"' not in xml, "old name column value still present"
    assert 'w:w="1095"' not in xml, "old method column value still present"
    assert 'w:right="1134"' not in xml, "old margin right still present"
