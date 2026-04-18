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


# ---------------------------------------------------------------------------
# Typography post-render substitution (T4 continuation)
# Tests call _apply_typography_overrides directly, bypassing build_preview_context
# (which would try to open the real on-disk DB).  We supply rendered DOCX bytes
# by rendering with a no-op context, then pass them through the override function.
# ---------------------------------------------------------------------------

def _template_bytes() -> bytes:
    """Return the raw on-disk DOCX template bytes (sentinels still present).

    _apply_typography_overrides tests must operate on the raw template so the
    sentinel value 999 is still present.  _docxtpl_render already calls
    _apply_typography_overrides internally, so rendered bytes have sentinels
    replaced and cannot be used to test non-default overrides.
    """
    from mbr.certs.generator import _TEMPLATE_PATH
    return _TEMPLATE_PATH.read_bytes()


def _read_xml(docx_bytes: bytes, member: str) -> str:
    """Extract and decode an XML member from a DOCX (zip) byte string."""
    import zipfile
    from io import BytesIO
    with zipfile.ZipFile(BytesIO(docx_bytes), "r") as z:
        return z.read(member).decode("utf-8")


def test_docx_typography_reflects_settings():
    """body_font_family setting flows into both document.xml and header1.xml."""
    from mbr.certs.generator import _apply_typography_overrides
    raw = _template_bytes()
    result = _apply_typography_overrides(raw, "EB Garamond", 14)
    doc_xml = _read_xml(result, "word/document.xml")
    hdr_xml = _read_xml(result, "word/header1.xml")
    assert "EB Garamond" in doc_xml, "custom font not in document.xml"
    assert "TeX Gyre Bonum" not in doc_xml, "body font literal still in document.xml"
    assert "EB Garamond" in hdr_xml, "custom font not in header1.xml"
    assert "Bookman Old Style" not in hdr_xml, "header font literal still in header1.xml"


def test_docx_header_size_reflects_settings():
    """header_font_size_pt flows into header w:sz / w:szCs and Nagwek8 style."""
    from mbr.certs.generator import _apply_typography_overrides
    raw = _template_bytes()
    # 20pt → 40 half-points
    result = _apply_typography_overrides(raw, "TeX Gyre Bonum", 20)
    hdr_xml = _read_xml(result, "word/header1.xml")
    sty_xml = _read_xml(result, "word/styles.xml")
    assert '<w:sz w:val="40"/>' in hdr_xml, "header sz=40 not found for 20pt"
    assert '<w:szCs w:val="40"/>' in hdr_xml, "header szCs=40 not found for 20pt"
    assert '<w:sz w:val="999"/>' not in hdr_xml, "sentinel sz still present in header"
    assert '<w:szCs w:val="999"/>' not in hdr_xml, "sentinel szCs still present in header"
    assert '<w:sz w:val="999"/>' not in sty_xml, "sentinel sz still present in styles"
    assert '<w:sz w:val="40"/>' in sty_xml, "Nagwek8 sz=40 not in styles for 20pt"


def test_docx_default_settings_produce_substituted_output():
    """Default settings (TeX Gyre Bonum, 14pt) replace sentinel with 28 half-points."""
    from mbr.certs.generator import _apply_typography_overrides
    raw = _template_bytes()
    result = _apply_typography_overrides(raw, "TeX Gyre Bonum", 14)
    hdr_xml = _read_xml(result, "word/header1.xml")
    sty_xml = _read_xml(result, "word/styles.xml")
    doc_xml = _read_xml(result, "word/document.xml")
    # Sentinels gone
    assert '<w:sz w:val="999"/>' not in hdr_xml, "sentinel sz leaked to header"
    assert '<w:szCs w:val="999"/>' not in hdr_xml, "sentinel szCs leaked to header"
    assert '<w:sz w:val="999"/>' not in sty_xml, "sentinel sz leaked to styles"
    # 14pt → 28 half-points
    assert '<w:sz w:val="28"/>' in hdr_xml, "header sz=28 (14pt default) not in header"
    assert '<w:szCs w:val="28"/>' in hdr_xml, "header szCs=28 not in header"
    assert '<w:sz w:val="28"/>' in sty_xml, "Nagwek8 sz=28 not in styles"
    # Body font unchanged (default == template literal)
    assert "TeX Gyre Bonum" in doc_xml, "default body font missing from document.xml"
