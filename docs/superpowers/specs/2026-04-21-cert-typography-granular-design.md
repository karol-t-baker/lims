# Cert Typography — Granular Header Controls + Sharp Logo

Status: Draft for user review
Date: 2026-04-21
Author: Claude Opus 4.7 (1M context) w/ Tbk

## Motivation

Operator complains:

1. One `header_font_size_pt` setting currently drives **all** runs in
   `word/header1.xml` (title + product name). They render at identical size;
   visual hierarchy has to come from font weight alone. Tweaking either one
   is impossible without also moving the other.
2. The logo (`word/media/image2.png`, 210×205 px @ 96 DPI) is upsampled when
   Gotenberg/LibreOffice rasterise the DOCX for PDF at 300+ DPI print. Edges
   are visibly soft.

Operator provides an SVG (`/Users/tbk/Downloads/logo.svg`, viewBox 1049×1024)
whose aspect ratio matches the current render area exactly (EMU 864000×843428
= 1.0244; SVG 1049/1024 = 1.0244). Drop-in replacement is possible.

## Goals

- Three independent size controls surfaced in the admin "Ustawienia globalne"
  modal: **Title**, **Product name**, **Body (table + text)**.
- Logo renders crisp at any print DPI up to 600 DPI without visible
  upsampling artifacts.
- No visual regression for users who already customised
  `header_font_size_pt`. Existing setting migrates into the new model.

## Non-goals

- Separate control for "/" separator or individual paragraph spacing.
- Body sub-controls (table-cell font vs. paragraph font). Body has exactly
  one functional size (`w:sz w:val="22"` = 11 pt) aside from the 1-pt
  (`w:val="2"`) spacer runs, which stay untouched.
- Bilingual title split (PL/EN each a different size). "ŚWIADECTWO JAKOŚCI"
  and "CERTIFICATE OF ANALYSIS" remain a single title block.
- SVG embedded as native SVG in DOCX. DOCX-native SVG support is uneven
  across LibreOffice versions. We rasterise at build-time to a high-res PNG.

## Design

### Data model — `cert_settings` table

Add three new keys (TEXT values; integer point size):

| Key                         | Default | Purpose                                 |
|-----------------------------|---------|-----------------------------------------|
| `title_font_size_pt`        | 12      | "ŚWIADECTWO JAKOŚCI / CERTIFICATE …"    |
| `product_name_font_size_pt` | 16      | `{{display_name}}` run                  |
| `body_font_size_pt`         | 11      | All body text — table + paragraphs      |

`header_font_size_pt` stays in the table as a deprecated fallback; removed
from admin UI. First-load migration (idempotent, guarded by "IS NULL" on the
new keys) reads the legacy value and copies it into both
`title_font_size_pt` and `product_name_font_size_pt`.

### Template — `cert_master_template.docx`

Current: sentinel `999` used by both `Nagwek4` (title) and `Nagwek8`
(product name) styles; the runtime substitution collapses them to the same
size. Split per style:

| Style       | Current sentinel | New sentinel | Used for                  |
|-------------|------------------|--------------|---------------------------|
| `Nagwek4`   | 999              | **996**      | "ŚWIADECTWO JAKOŚCI / …"  |
| `Nagwek8`   | 999              | **997**      | `{{display_name}}`        |

Changes, in-place:

- `word/styles.xml`: `Nagwek4` `w:sz w:val="999"` → `996`;
  `Nagwek8` `w:sz w:val="999"` → `997`.
- `word/header1.xml`: each inline `w:szCs w:val="999"` rewritten based on
  the containing `pStyle` (paragraphs with `pStyle="Nagwek4"` → `996`,
  `pStyle="Nagwek8"` → `997`). There are 12 occurrences; one-time patch.

`word/document.xml` unchanged — body keeps its existing `w:sz w:val="22"`
and `w:szCs w:val="22"`; generator rewrites them at render time.

### Runtime — `mbr/certs/generator.py`

`_apply_typography_overrides(docx_bytes, font, sizes)` — existing function
extended to take a `sizes` dict instead of single `header_size_pt`:

```python
sizes = {
    "title_pt":        title_font_size_pt,
    "product_name_pt": product_name_font_size_pt,
    "body_pt":         body_font_size_pt,
}
```

Substitutions, byte-level on unzipped XML:

- `word/header1.xml`:
  - `<w:sz w:val="996"/>`  → `<w:sz w:val="{title_pt*2}"/>`
  - `<w:szCs w:val="996"/>` → `<w:szCs w:val="{title_pt*2}"/>`
  - `<w:sz w:val="997"/>`  → `<w:sz w:val="{product_name_pt*2}"/>`
  - `<w:szCs w:val="997"/>` → `<w:szCs w:val="{product_name_pt*2}"/>`
- `word/styles.xml`:
  - `<w:sz w:val="996"/>` → `<w:sz w:val="{title_pt*2}"/>`
  - `<w:sz w:val="997"/>` → `<w:sz w:val="{product_name_pt*2}"/>`
- `word/document.xml`:
  - `<w:sz w:val="22"/>`   → `<w:sz w:val="{body_pt*2}"/>`
  - `<w:szCs w:val="22"/>` → `<w:szCs w:val="{body_pt*2}"/>`
  - `w:val="2"` (1-pt spacers) is NOT touched — regex uses exact `"22"`.

`_load_cert_settings(db)` returns a dict with the three new keys; the old
`header_font_size_pt` is still loaded but not forwarded to the renderer.

### Migration

At app startup, `init_mbr_tables` (or a new `init_cert_typography_migration`
called from `create_app`) runs once:

```sql
INSERT OR IGNORE INTO cert_settings (key, value)
VALUES
  ('title_font_size_pt',
   COALESCE((SELECT value FROM cert_settings WHERE key='header_font_size_pt'), '12')),
  ('product_name_font_size_pt',
   COALESCE((SELECT value FROM cert_settings WHERE key='header_font_size_pt'), '16')),
  ('body_font_size_pt', '11');
```

Idempotent. Running on fresh DB uses defaults (12/16/11). Running on prod
where `header_font_size_pt=12` copies 12 into both `title_font_size_pt`
and `product_name_font_size_pt` — legacy certs rendered immediately after
deploy look identical to pre-deploy (title 12pt, product 12pt, body 11pt
unchanged). Operator can then bump product name to 16pt (or any value)
without touching title.

### Admin UI — `/admin/wzory-cert` "Ustawienia globalne" modal

Replace the single "Rozmiar czcionki w nagłówku (pt)" input with three:

```
┌─ Typografia ─────────────────────────────────┐
│ Tytuł (pt):            [18] ▲▼              │
│ Nazwa produktu (pt):   [16] ▲▼              │
│ Body — tabela + tekst: [11] ▲▼              │
└──────────────────────────────────────────────┘
```

PUT /api/cert/settings accepts the three new keys (int 6–36, validated
server-side; out-of-range returns 400). Legacy `header_font_size_pt`
rejected on write.

### Logo — SVG → high-res PNG

Build-time (ad-hoc script, run once):

```python
import cairosvg
cairosvg.svg2png(
    url='/Users/tbk/Downloads/logo.svg',
    write_to='mbr/templates/_logo_1200.png',
    output_width=1200, output_height=1172,  # aspect 1049:1024 ≈ 1.0244
)
```

Then unzip `cert_master_template.docx`, replace `word/media/image2.png`
with the new PNG, rezip. Display dimensions in `header1.xml`
(`cx="864000" cy="843428"` EMU → 2.40×2.34 cm) unchanged — LibreOffice
downsamples 1200 px → ~280 px at 300 DPI print, giving sharp edges.

The SVG source file is also committed to `mbr/templates/_logo_source.svg`
so future rebuilds don't depend on the user's Downloads folder.

### Tests

New file `tests/test_cert_typography_granular.py`:

- `_apply_typography_overrides` substitutes sentinel `996` when title size
  changes; `997` when product name changes; body `22` when body size
  changes. Verifies `w:val="2"` is NOT affected by body substitution.
- Migration: seed `cert_settings` with only `header_font_size_pt=14` →
  run migration → `title_font_size_pt=14` AND
  `product_name_font_size_pt=14` present; `body_font_size_pt=11`.
- Migration idempotency: run twice, values stable.
- `PUT /api/cert/settings` accepts three new keys (200); payload containing
  legacy `header_font_size_pt` is silently ignored (key removed from the
  validated whitelist, not rejected with 400 — safer for any lingering
  client-side caches still sending the old field).
- `PUT /api/cert/settings` validates range 6–36 (400 on out-of-range).

Existing cert-render tests should keep passing — no visual regression if
migration fires before first render.

## Risks

- **Sentinel collision**: 996/997 values must not appear anywhere else in
  the template. Verified at spec-write time by unzipping
  `cert_master_template.docx` and grepping for `w:val="996"` and
  `w:val="997"` — both return 0 occurrences. Only `999` is present
  (header1.xml + styles.xml), which we rewrite to 996/997 in this change.
- **Body regex specificity**: replacing `w:val="22"` relies on exact
  4-char match; a future document.xml with values like `w:val="220"`
  (not currently present) would need safer regex. Today's template has
  only `2` and `22` — safe.
- **SVG rendering portability**: `cairosvg` depends on libcairo. Available
  on the dev machine (verified). Not required at runtime on prod — we
  render once at build-time into PNG, commit the PNG in the template.
- **Bilingual title edge case**: user later says they want PL and EN at
  different sizes — out of scope here, revisit as a follow-up.

## Open questions

None at draft time. All three user-facing decisions confirmed:

- Typography model: 3 controls (title / product name / body).
- Logo: SVG → 1200×1172 PNG, template asset replaced.
- Defaults: 12 / 16 / 11 pt (confirmed in chat 2026-04-21).
- Legacy `header_font_size_pt` on PUT: silently ignored (not 400).
- Bilingual title PL/EN split: out of scope — single shared
  `title_font_size_pt` covers both lines.

## Rollout

1. Admin Y (no change) — deploy is safe thanks to migration.
2. Verify current cert rendering unchanged for existing
   `header_font_size_pt=12` prod setup.
3. Tell operator they can now tune the three values independently.
