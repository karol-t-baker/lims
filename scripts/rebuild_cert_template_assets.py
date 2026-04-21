"""Rebuild cert_master_template.docx assets from SVG + sentinel scheme.

Idempotent: running multiple times produces the same template. Touches two
things inside the DOCX:

  1. word/media/image2.png — replaced with 1200×1172 PNG rendered from
     mbr/templates/_logo_source.svg via cairosvg. Aspect 1049:1024 matches
     the current render area (864000:843428 EMU) exactly, so no layout
     shift; only sharpness improves.

  2. Sentinels — word/styles.xml: Nagwek4 w:sz w:val="999" → "996";
     Nagwek8 w:sz w:val="999" → "997". word/header1.xml: inline
     w:szCs w:val="999" rewritten based on the containing pStyle:
     paragraphs using pStyle="Nagwek4" → 996; pStyle="Nagwek8" → 997.

Run:  python scripts/rebuild_cert_template_assets.py
"""

from __future__ import annotations

import io
import re
import shutil
import sys
import zipfile
from pathlib import Path

import cairosvg

ROOT = Path(__file__).resolve().parent.parent
SVG_SRC = ROOT / "mbr" / "templates" / "_logo_source.svg"
DOCX_PATH = ROOT / "mbr" / "templates" / "cert_master_template.docx"

LOGO_WIDTH = 1200
LOGO_HEIGHT = 1172  # 1200 * (1024/1049), rounded; keeps aspect 1.0244


def render_logo_png() -> bytes:
    """Render the vendored SVG to PNG at 1200×1172."""
    return cairosvg.svg2png(
        url=str(SVG_SRC),
        output_width=LOGO_WIDTH,
        output_height=LOGO_HEIGHT,
    )


def patch_styles_xml(xml: str) -> str:
    """Swap sentinel 999 to style-specific values in styles.xml.

    Only the Nagwek4 and Nagwek8 <w:style> blocks carry w:sz="999"; we replace
    inside those blocks only (not globally, so future styles adding the same
    literal are not silently mutated).
    """
    def replace_in_block(style_id: str, new_val: str) -> None:
        nonlocal xml
        pattern = (
            r'(<w:style\s[^>]*w:styleId="' + re.escape(style_id) + r'"[^>]*>.*?</w:style>)'
        )
        m = re.search(pattern, xml, re.DOTALL)
        if not m:
            raise RuntimeError(f"style {style_id!r} not found in styles.xml")
        block = m.group(1)
        new_block = block.replace('w:sz w:val="999"', f'w:sz w:val="{new_val}"')
        if block == new_block:
            # Already patched (idempotent) or sentinel missing — log.
            print(f"  {style_id}: no sentinel 999 found (already patched or missing)")
        xml = xml.replace(block, new_block)

    replace_in_block("Nagwek4", "996")
    replace_in_block("Nagwek8", "997")
    return xml


def patch_header_xml(xml: str) -> str:
    """Rewrite inline w:sz and w:szCs w:val="999" per containing pStyle.

    Each <w:p> ... </w:p> block is inspected: if it contains
    <w:pStyle w:val="Nagwek4"/> → child 999 becomes 996; Nagwek8 → 997.
    Both w:sz and w:szCs attributes are rewritten.
    """
    paragraph_re = re.compile(r'<w:p(?:\s[^>]*)?>.*?</w:p>', re.DOTALL)

    def rewrite_paragraph(match: re.Match) -> str:
        p = match.group(0)
        if '<w:pStyle w:val="Nagwek4"' in p:
            p = p.replace('w:szCs w:val="999"', 'w:szCs w:val="996"')
            p = p.replace('w:sz w:val="999"', 'w:sz w:val="996"')
            return p
        if '<w:pStyle w:val="Nagwek8"' in p:
            p = p.replace('w:szCs w:val="999"', 'w:szCs w:val="997"')
            p = p.replace('w:sz w:val="999"', 'w:sz w:val="997"')
            return p
        return p

    return paragraph_re.sub(rewrite_paragraph, xml)


def rebuild_docx() -> None:
    """Patch DOCX in place: replace image2.png and rewrite XML sentinels."""
    if not SVG_SRC.exists():
        sys.exit(f"SVG source missing: {SVG_SRC}")
    if not DOCX_PATH.exists():
        sys.exit(f"DOCX missing: {DOCX_PATH}")

    png_bytes = render_logo_png()
    print(f"Rendered logo PNG: {len(png_bytes)} bytes ({LOGO_WIDTH}×{LOGO_HEIGHT})")

    in_buf = io.BytesIO(DOCX_PATH.read_bytes())
    out_buf = io.BytesIO()

    with zipfile.ZipFile(in_buf, "r") as zin, \
         zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.namelist():
            data = zin.read(item)
            if item == "word/media/image2.png":
                data = png_bytes
                print(f"  replaced {item} ({len(png_bytes)} bytes)")
            elif item == "word/styles.xml":
                txt = data.decode("utf-8")
                new_txt = patch_styles_xml(txt)
                if new_txt != txt:
                    print(f"  patched {item} (sentinel 999 → 996/997)")
                data = new_txt.encode("utf-8")
            elif item == "word/header1.xml":
                txt = data.decode("utf-8")
                new_txt = patch_header_xml(txt)
                if new_txt != txt:
                    print(f"  patched {item} (inline szCs 999 → 996/997)")
                data = new_txt.encode("utf-8")
            zout.writestr(item, data)

    shutil.move(DOCX_PATH, DOCX_PATH.with_suffix(".docx.bak"))
    DOCX_PATH.write_bytes(out_buf.getvalue())
    print(f"Wrote {DOCX_PATH} (old saved as {DOCX_PATH.with_suffix('.docx.bak').name})")


if __name__ == "__main__":
    rebuild_docx()
