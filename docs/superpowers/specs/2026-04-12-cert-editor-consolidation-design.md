# Certificate Editor Consolidation & Redesign

**Date**: 2026-04-12
**Status**: Draft
**Goal**: Merge two certificate editor UIs into one intuitive, non-technical editor with clean styling.

## Problem

Admin has cert editing in two places:
1. `/admin/wzory-cert` — full editor (variants, preview, metadata, parameters)
2. Tab "Świadectwa" in `/parametry` — simple CRUD for base cert parameters

Both edit `parametry_cert`. The full editor is a superset but is too dense, uses technical jargon, and mixes too many concerns in one view.

## Users

- Admin (configuration)
- Kierownik KJ (quality manager)
- Technolog (process engineer)

Usage pattern: intensive configuration initially, then sporadic edits. UX must be intuitive on first use — clear labels, logical grouping, no technical jargon.

## Design

### Navigation

Remove tab "Świadectwa" from parametry_editor.html. Keep `/admin/wzory-cert` as the single cert editor, accessible from admin nav rail.

### Layout: 3-tab editor

Product selector at top (dropdown with product list). Below: 3 tabs.

#### Tab 1: Produkt (metadata)

Simple form, ~6 fields:

| Label | Field | Current name |
|---|---|---|
| Nazwa wyświetlana | text input | `display_name` |
| Numer specyfikacji | text input | `spec_number` |
| Numer CAS | text input | `cas_number` |
| Ważność (miesiące) | number input | `expiry_months` |
| Opinia jakościowa (PL) | textarea | `opinion_pl` |
| Opinia jakościowa (EN) | textarea | `opinion_en` |

#### Tab 2: Parametry świadectwa

Table with human-readable columns:

| Column label | Source | Editable | Notes |
|---|---|---|---|
| Parametr | `parametry_analityczne.label` | read-only | drag handle for reorder |
| Nazwa na świadectwie (PL) | `name_pl` override or label | yes | defaults to global label |
| Nazwa na świadectwie (EN) | `name_en` override or pa.name_en | yes | |
| Wymaganie | `requirement` | yes | e.g. "min 35,5" |
| Metoda | `method` override or pa.method_code | yes | e.g. "L903" |
| Miejsca po przecinku | dropdown 0/1/2/3 | yes | replaces "format" |
| Wynik opisowy | text or empty | yes | replaces "qualitative_result"; if filled, numeric result is ignored |

"+ Dodaj parametr" button opens inline form:
- Dropdown: "Wybierz parametr" — lists parametry_analityczne that are in analiza_koncowa for this product but not yet on cert
- Pre-fills name PL/EN from the selected parameter
- User fills requirement, method, format

Superscript/subscript support stays (for names like n_{D}^{20}) but with a help tooltip explaining syntax.

#### Tab 3: Warianty świadectw

Each variant as an expandable card:

**Card header**: variant label + edit/delete buttons

**Card body**:
- Nazwa wariantu: text input
- Opcje (checkboxy z opisami):
  - "Pokaż numer zamówienia" (`has_order_number`)
  - "Pokaż numer certyfikatu" (`has_certificate_number`)
  - "Logo RSPO" (`has_rspo`)
  - "Kod Avon" (`has_avon_code`) — shows avon_code + avon_name fields when checked
- Nadpisania (opcjonalne):
  - Numer specyfikacji (override)
  - Opinia PL (override)
  - Opinia EN (override)
- Ukryj parametry: list of checkboxes with parameter names (human-readable). Checked = removed from this variant. Replaces raw `remove_params` ID array.
- Dodatkowe parametry: mini-table same structure as Tab 2. For variant-specific parameters.

"+ Nowy wariant" button at bottom.

### PDF Preview

Button "Podgląd PDF" in the editor header area (always visible). Opens modal:
- Dropdown: select variant to preview
- iframe with generated PDF
- "Odśwież" button
- Close button

### Styling

Use `frontend-design` skill for implementation. Design constraints:
- Follow existing app design system (CSS vars: `--teal`, `--surface`, `--border`, `--text-dim`, etc.)
- Match the visual language of existing admin pages (audit panel, parametry editor)
- Clean, spacious layout — generous padding, clear section boundaries
- Mobile-friendly is not required (admin desktop only)

### Data source

After Phase 1 of parameter centralization:
- Tab 2 reads/writes `parametry_etapy` (columns `on_cert`, `cert_requirement`, `cert_format`, `cert_qualitative_result`, `cert_kolejnosc`)
- Tab 3 reads/writes `cert_variants` + `parametry_etapy WHERE kontekst='cert_variant'`
- Tab 1 reads/writes `produkty`
- Fallback to `parametry_cert` until Phase 4 cleanup

### Removal

- Delete tab "Świadectwa" (index 2) from `mbr/templates/parametry_editor.html` (HTML lines ~226-270, JS lines ~566-679)
- Delete API routes in `mbr/parametry/routes.py` lines 327-408 (`/api/parametry/cert/*`)
- These endpoints are fully replaced by `/api/cert/config/*` in `mbr/certs/routes.py`

## Files Affected

| File | Change |
|---|---|
| `mbr/templates/admin/wzory_cert.html` | Full rewrite — 3-tab layout, polish labels, modal preview |
| `mbr/templates/parametry_editor.html` | Remove Świadectwa tab (HTML + JS) |
| `mbr/parametry/routes.py` | Remove `/api/parametry/cert/*` endpoints |
| `mbr/certs/routes.py` | Update PUT endpoint to work with new editor structure |
| `mbr/static/style.css` | New styles for cert editor (via frontend-design skill) |

## Constraints

- No backend API changes needed — existing `/api/cert/config/*` endpoints handle everything
- Cert PDF output unchanged — only the editor UI changes
- All existing cert data preserved — no migration needed (data already in DB)
- Product selector: only products with `cert_variants` entries shown (as currently)
