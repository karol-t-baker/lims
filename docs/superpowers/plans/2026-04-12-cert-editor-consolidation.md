# Certificate Editor Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate two cert editors into one redesigned 3-tab UI with Polish labels, remove redundant code.

**Architecture:** Remove "Świadectwa" tab + API routes from parametry_editor. Rewrite `wzory_cert.html` as 3-tab layout (Produkt / Parametry / Warianty) with modal PDF preview. Use `frontend-design` skill for the HTML/CSS rewrite.

**Tech Stack:** Flask, Jinja2, vanilla JS, CSS (existing design system variables)

**Spec:** `docs/superpowers/specs/2026-04-12-cert-editor-consolidation-design.md`

---

### Task 1: Remove "Świadectwa" tab from parametry_editor

**Files:**
- Modify: `mbr/templates/parametry_editor.html`
- Modify: `mbr/parametry/routes.py`

- [ ] **Step 1: Remove cert tab button from tab strip**

In `mbr/templates/parametry_editor.html`, delete lines 130-132:

```html
    {% if is_admin %}
    <button class="pe-tab" id="tab-cert" onclick="switchTab('cert')">Świadectwa</button>
    {% endif %}
```

- [ ] **Step 2: Remove cert panel HTML**

Delete lines 226-270 (the `<div id="panel-cert">` block including the closing `{% endif %}`):

```html
  {% if is_admin %}
  <div id="panel-cert" style="display:none;">
    ...entire cert panel...
  </div>
  {% endif %}
```

- [ ] **Step 3: Remove cert JS section**

Delete lines 566-679 — everything from `var _certLoaded = false;` through the `certDrop` function, up to (but not including) `// ═══ PRODUKTY TAB ═══`.

- [ ] **Step 4: Update switchTab to remove 'cert' from tab list**

Change line 458 from:

```javascript
  ['bind', 'def', 'cert', 'prod'].forEach(function(t) {
```

To:

```javascript
  ['bind', 'def', 'prod'].forEach(function(t) {
```

And delete line 465:

```javascript
  if (which === 'cert' && !_certLoaded) loadCertAvailable();
```

- [ ] **Step 5: Remove cert API routes from parametry/routes.py**

Delete the 5 routes in `mbr/parametry/routes.py` lines 327-408:

- `GET /api/parametry/cert/<produkt>` (api_parametry_cert_list)
- `POST /api/parametry/cert` (api_parametry_cert_create)
- `PUT /api/parametry/cert/<int:binding_id>` (api_parametry_cert_update)
- `DELETE /api/parametry/cert/<int:binding_id>` (api_parametry_cert_delete)
- `POST /api/parametry/cert/reorder` (api_parametry_cert_reorder)

Also remove `cert_products` from the `parametry_editor()` view function context if it's passed:

Check `mbr/parametry/routes.py` around line 483-502 for the view function and remove `cert_products` from the template context.

- [ ] **Step 6: Remove the delete button CSS comment referencing cert tab**

In `mbr/templates/parametry_editor.html` line 23, change:

```css
/* Delete button — used by cert tab too */
```

To:

```css
/* Delete button */
```

- [ ] **Step 7: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: all pass. No tests should reference `/api/parametry/cert/` endpoints.

- [ ] **Step 8: Verify in browser**

Start: `python -m mbr.app`
Navigate to `/parametry` as admin. Verify:
- Tab strip shows: Etapy | Rejestr | Produkty (no "Świadectwa")
- All three remaining tabs work normally
- `/admin/wzory-cert` still works (untouched)

- [ ] **Step 9: Commit**

```bash
git add mbr/templates/parametry_editor.html mbr/parametry/routes.py
git commit -m "refactor: remove redundant Świadectwa tab from parametry editor"
```

---

### Task 2: Rewrite `wzory_cert.html` — 3-tab layout with Polish labels

**Files:**
- Rewrite: `mbr/templates/admin/wzory_cert.html`

**IMPORTANT:** Use the `frontend-design` skill for this task. The template needs to be completely rewritten with:

**Design requirements (from spec):**

1. **Product selector** at top — dropdown listing all cert-enabled products

2. **Tab 1: Produkt** — simple form with Polish labels:
   - Nazwa wyświetlana, Numer specyfikacji, Numer CAS, Ważność (miesiące)
   - Opinia jakościowa (PL), Opinia jakościowa (EN)

3. **Tab 2: Parametry świadectwa** — table with columns:
   - Parametr (read-only, from `parametry_analityczne.label`)
   - Nazwa na świadectwie (PL) — editable, defaults to label
   - Nazwa na świadectwie (EN) — editable
   - Wymaganie — editable text
   - Metoda — editable text
   - Miejsca po przecinku — dropdown 0/1/2/3
   - Wynik opisowy — text input (empty = numeric result used)
   - Drag handle for reorder, delete button
   - "+ Dodaj parametr" button — dropdown shows analiza_koncowa params not yet on cert

4. **Tab 3: Warianty świadectw** — expandable cards:
   - Each card: Nazwa wariantu, option checkboxes with Polish labels
   - "Ukryj parametry" — checkboxes with parameter names (not IDs)
   - "Dodatkowe parametry" — mini-table same as Tab 2
   - Override fields: Numer specyfikacji, Opinia PL/EN
   - "+ Nowy wariant" button

5. **PDF Preview modal** — button "Podgląd PDF" in header:
   - Modal with variant dropdown + iframe + refresh button

**Styling constraints:**
- Use existing CSS variables: `--teal`, `--surface`, `--surface-alt`, `--border`, `--text`, `--text-dim`, `--text-sec`
- Match visual language of existing admin pages (audit panel, parametry editor)
- Clean, spacious layout — generous padding, clear section boundaries
- `.modal-overlay` class exists in `style.css` for modals

**API endpoints** (all existing, no changes needed):
- `GET /api/cert/config/products` — product list
- `GET /api/cert/config/product/<key>` — full product config
- `PUT /api/cert/config/product/<key>` — save all (parameters + variants)
- `POST /api/cert/config/preview` — generate PDF preview
- `GET /api/parametry/available?produkt=<key>` — available params for adding

**Current file structure for reference:**
- Template extends `base.html`
- `{% block topbar_title %}` for page title
- `{% block content %}` for main content
- `{% block scripts %}` not used (JS is inline)

- [ ] **Step 1: Read current `wzory_cert.html` fully**

Read the entire file to understand current JS logic (API calls, state management, collectEditorState, saveProduct).

- [ ] **Step 2: Rewrite the template using frontend-design skill**

Invoke the `frontend-design` skill with the design requirements above. The skill will generate the complete HTML/CSS/JS for the template.

Key JS functions to preserve (same logic, cleaner code):
- `loadProducts()` — fetch product list, render cards/dropdown
- `loadProduct(key)` — fetch full config, populate all tabs
- `collectEditorState()` — gather all form data into JSON
- `saveProduct()` — PUT to API
- `openPreviewModal()` / `refreshPreview()` — PDF preview

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: all pass

- [ ] **Step 4: Verify in browser**

Start dev server. Navigate to `/admin/wzory-cert` as admin:
- Product selector works, loads product data
- Tab 1 (Produkt): metadata form renders and saves
- Tab 2 (Parametry): table renders, inline edits work, drag reorder works, add/remove works
- Tab 3 (Warianty): cards render, checkboxes work, add/remove variant works
- PDF Preview modal opens, renders PDF, variant selector works
- Save button works without errors

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat: redesigned cert editor — 3-tab layout with Polish labels and modal preview"
```

---

### Task 3: Final push

**Files:**
- No file changes

- [ ] **Step 1: Run full test suite one more time**

Run: `pytest tests/ -x -q`
Expected: all pass

- [ ] **Step 2: Push**

```bash
git push origin main
```

---

## Verification Checklist

After all tasks:
1. `/parametry` has no "Świadectwa" tab
2. `/admin/wzory-cert` has 3-tab layout: Produkt | Parametry | Warianty
3. All labels are in Polish, human-readable
4. PDF preview opens as modal
5. Saving works (PUT `/api/cert/config/product/<key>`)
6. No `/api/parametry/cert/*` routes exist
7. All existing tests pass
8. Certificate PDF generation unchanged
