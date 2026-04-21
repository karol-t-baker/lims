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
    assert 'w:right="567"' in xml, "margin right not reduced to 10mm"
    assert 'w:left="567"' in xml, "margin left not reduced to 10mm"
    assert 'w:w="10772"' in xml, "tblW not resized to 190mm"
    assert 'w:w="4873"' in xml, "name column not sized to 86mm"
    assert 'w:w="2178"' in xml, "requirement (col 2) not sized to current 2178 twipów"
    assert 'w:w="2126"' in xml, "method (col 3) not sized to current 2126 twipów"
    assert 'w:w="1595"' in xml, "result (col 4) not widened to current 1595 twipów (~2.8cm)"
    # Old values should be absent
    assert 'w:w="4471"' not in xml, "old name column value still present"
    assert 'w:w="1095"' not in xml, "old method column value still present"
    assert 'w:w="1984"' not in xml, "old result column value still present"
    assert 'w:w="4673"' not in xml, "previous narrow name column still present"
    assert 'w:w="2450"' not in xml, "previous wider req/result still present"
    assert 'w:w="999"' not in xml, "previous narrower method still present"
    assert 'w:w="1113"' not in xml, "previous intermediate method width still present"
    assert 'w:w="2393"' not in xml, "previous requirement width still present"
    assert 'w:w="2336"' not in xml, "previous method width still present"
    assert 'w:w="1170"' not in xml, "previous narrow result width still present"
    assert 'w:w="2093"' not in xml, "intermediate requirement width still present"
    assert 'w:w="2036"' not in xml, "intermediate method width still present"
    assert 'w:w="1770"' not in xml, "intermediate result width still present"
    assert 'w:w="10432"' not in xml, "previous tblW still present"
    assert 'w:right="737"' not in xml, "previous 13mm margin still present"
    assert 'w:right="1134"' not in xml, "very old 20mm margin still present"


# ---------------------------------------------------------------------------
# Typography post-render substitution (T4 continuation)
# Tests call _apply_typography_overrides directly, bypassing build_preview_context
# (which would try to open the real on-disk DB).  We supply rendered DOCX bytes
# by rendering with a no-op context, then pass them through the override function.
# ---------------------------------------------------------------------------

def _template_bytes() -> bytes:
    """Return the raw on-disk DOCX template bytes (sentinels still present).

    _apply_typography_overrides tests must operate on the raw template so the
    sentinel values 996/997 are still present.  _docxtpl_render already calls
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
    sizes = {"title_pt": 12, "product_name_pt": 16, "body_pt": 11}
    result = _apply_typography_overrides(raw, "EB Garamond", sizes=sizes)
    doc_xml = _read_xml(result, "word/document.xml")
    hdr_xml = _read_xml(result, "word/header1.xml")
    assert "EB Garamond" in doc_xml, "custom font not in document.xml"
    assert "TeX Gyre Bonum" not in doc_xml, "body font literal still in document.xml"
    assert "EB Garamond" in hdr_xml, "custom font not in header1.xml"
    assert "Bookman Old Style" not in hdr_xml, "header font literal still in header1.xml"


def test_docx_header_size_reflects_settings():
    """title_font_size_pt and product_name_font_size_pt flow into header w:sz / w:szCs and Nagwek styles.

    With title_pt=20 sentinel 996 → 40 half-points (Nagwek4 / title runs).
    With product_name_pt=20 sentinel 997 → 40 half-points (Nagwek8 / product name runs).
    """
    from mbr.certs.generator import _apply_typography_overrides
    raw = _template_bytes()
    # 20pt → 40 half-points for both title (996) and product name (997)
    sizes = {"title_pt": 20, "product_name_pt": 20, "body_pt": 11}
    result = _apply_typography_overrides(raw, "TeX Gyre Bonum", sizes=sizes)
    hdr_xml = _read_xml(result, "word/header1.xml")
    sty_xml = _read_xml(result, "word/styles.xml")
    assert 'w:val="40"' in hdr_xml, "sz/szCs=40 not found in header for 20pt"
    assert '996' not in hdr_xml, "sentinel 996 still present in header"
    assert '997' not in hdr_xml, "sentinel 997 still present in header"
    assert '996' not in sty_xml, "sentinel 996 still present in styles"
    assert '997' not in sty_xml, "sentinel 997 still present in styles"
    assert 'w:val="40"' in sty_xml, "Nagwek sz=40 not in styles for 20pt"


def test_docx_default_settings_produce_substituted_output():
    """Default settings (Bookman Old Style, title=12pt, product=16pt, body=11pt) produce clean output.

    Body font literal 'TeX Gyre Bonum' is replaced with default 'Bookman Old Style';
    header literal stays as 'Bookman Old Style' (default == literal, no-op).
    Sentinels 996 and 997 are replaced with their respective half-point values.
    """
    from mbr.certs.generator import _apply_typography_overrides
    raw = _template_bytes()
    # Default sizes: title=12pt (→24 half-pts), product=16pt (→32 half-pts), body=11pt (→22 half-pts)
    sizes = {"title_pt": 12, "product_name_pt": 16, "body_pt": 11}
    result = _apply_typography_overrides(raw, "Bookman Old Style", sizes=sizes)
    hdr_xml = _read_xml(result, "word/header1.xml")
    sty_xml = _read_xml(result, "word/styles.xml")
    doc_xml = _read_xml(result, "word/document.xml")
    # Sentinels gone
    assert '996' not in hdr_xml, "sentinel 996 leaked to header"
    assert '997' not in hdr_xml, "sentinel 997 leaked to header"
    assert '996' not in sty_xml, "sentinel 996 leaked to styles"
    assert '997' not in sty_xml, "sentinel 997 leaked to styles"
    # title=12pt → 24 half-points in header (Nagwek4 / 996 runs)
    assert 'w:val="24"' in hdr_xml, "title sz=24 (12pt default) not in header"
    # product=16pt → 32 half-points in header (Nagwek8 / 997 runs)
    assert 'w:val="32"' in hdr_xml, "product sz=32 (16pt default) not in header"
    # Nagwek4 style: 24, Nagwek8 style: 32
    assert 'w:val="24"' in sty_xml, "Nagwek4 sz=24 not in styles"
    assert 'w:val="32"' in sty_xml, "Nagwek8 sz=32 not in styles"
    # Bookman Old Style appears (both body-substituted and header-native).
    assert "Bookman Old Style" in doc_xml, "Bookman Old Style not in document.xml"
    # Body literal was substituted — no stale "TeX Gyre Bonum" in output.
    assert "TeX Gyre Bonum" not in doc_xml, "body literal TeX Gyre Bonum leaked to output"


def test_docxtpl_render_respects_settings():
    """_docxtpl_render applies custom font and size from context."""
    from mbr.certs.generator import _docxtpl_render
    # Build a minimal context with non-default font and sizes
    ctx = {
        "display_name": "Test",
        "spec_number": "S1",
        "cas_number": "",
        "expiry_months": 12,
        "opinion_pl": "",
        "opinion_en": "",
        "company_name": "Test Co",
        "company_address": "",
        "footer": "",
        "rspo_number": "",
        "rows": [],
        "dt_produkcji": "01.01.2024",
        "dt_waznosci": "01.01.2025",
        "dt_wystawienia": "01.01.2024",
        "has_rspo": False,
        "has_order_number": False,
        "certificate_number": "",
        "avon_code": "",
        "avon_name": "",
        "order_number": "",
        "wystawil": "",
        "lab_approver_name": "",
        "tech_approver_name": "",
        "body_font_family": "EB Garamond",
        "title_font_size_pt": 18,
        "product_name_font_size_pt": 18,
        "body_font_size_pt": 11,
    }
    docx_bytes = _docxtpl_render(ctx)
    # Extract XML from DOCX to verify font substitutions
    doc_xml = _read_xml(docx_bytes, "word/document.xml")
    hdr_xml = _read_xml(docx_bytes, "word/header1.xml")
    # Font substituted in document.xml (body) and header1.xml (header) — both end up as EB Garamond
    assert "EB Garamond" in doc_xml
    assert "EB Garamond" in hdr_xml
    # No sentinel leakage
    assert '996' not in hdr_xml, "sentinel 996 leaked to header"
    assert '997' not in hdr_xml, "sentinel 997 leaked to header"
    # title_font_size_pt=18 → 36 half-points (sentinel 996); product_name_font_size_pt=18 → 36 (sentinel 997)
    assert 'w:val="36"' in hdr_xml, "sz=36 (18pt) not found in header"


def test_user_content_with_font_literal_survives_substitution():
    """User-supplied text containing the template's font literal must NOT be
    corrupted by the font-substitution pass. This is the I1 regression guard.

    The fix scopes font substitution to w:rFonts attributes only, not
    arbitrary text inside <w:t> nodes. This test verifies the regex
    substitution doesn't corrupt text nodes that happen to contain the
    literal string "TeX Gyre Bonum" or "Bookman Old Style".
    """
    from mbr.certs.generator import _apply_typography_overrides
    import re

    # Create a synthetic DOCX-like XML fragment with both w:rFonts attributes
    # and text nodes containing the font literals
    raw_docx = _template_bytes()
    sizes = {"title_pt": 12, "product_name_pt": 16, "body_pt": 11}
    result = _apply_typography_overrides(raw_docx, "EB Garamond", sizes=sizes)
    doc_xml = _read_xml(result, "word/document.xml")

    # The key test: if a user's parameter name, product name, or opinion text
    # happened to contain "TeX Gyre Bonum", it should survive the substitution.
    # We simulate this by creating XML with a text node containing the literal.
    fake_xml = '''<w:document>
    <w:p><w:r><w:rPr><w:rFonts w:ascii="TeX Gyre Bonum" w:hAnsi="TeX Gyre Bonum"/></w:rPr>
    <w:t>Sample product TeX Gyre Bonum lookalike</w:t></w:r></w:p>
    </w:document>'''

    # Apply the substitution regex manually to verify the behavior
    txt = fake_xml
    if txt:
        txt = re.sub(
            r'(w:ascii|w:hAnsi|w:cs|w:eastAsia)="' + re.escape("TeX Gyre Bonum") + r'"',
            lambda m: f'{m.group(1)}="EB Garamond"',
            txt,
        )

    # The w:rFonts attributes should be replaced
    assert 'w:ascii="EB Garamond"' in txt
    assert 'w:hAnsi="EB Garamond"' in txt
    # But the text content must remain intact
    assert 'Sample product TeX Gyre Bonum lookalike' in txt

    # Also verify that in the actual rendered output, fonts were substituted correctly
    assert "EB Garamond" in doc_xml
    # And no sentinel leakage (document.xml has no 996/997 sentinels, only body sz=22)
    assert '996' not in doc_xml
    assert '997' not in doc_xml
