# Cert Alias — Design Spec

**Date:** 2026-04-19
**Status:** Approved for implementation
**Scope:** ~4-6 hours of implementation (one table + routes + small UI addition).

## Problem

`Chegina_K40GLOL` and `Chegina_GLOL40` refer to the same physical product. Only `Chegina_K40GLOL` is actually produced in the plant (has its own pipeline, MBR, ebr_batches). `Chegina_GLOL40` exists in the DB solely as a cert persona — it has `cert_variants` rows (base, mb, nr_zam, oqema) and `parametry_cert` rows (10 base params), but no batches.

Today a K40GLOL batch can only issue cert variants owned by Chegina_K40GLOL. There is no way to print a GLOL40-branded cert for a K40GLOL batch.

## Goal

Let the admin declare a "cert alias" relationship `(source_produkt → target_produkt)`. When a batch's product has a cert alias configured:

1. The variant picker shows union: source's own variants + every alias target's variants.
2. Generating a cert for an aliased variant fills the PDF with target_produkt's branding/config and source batch's measurements (`ebr_wyniki`).
3. `cert_master_template.docx` stays the same — only the context differs.

No visual distinction between own vs aliased variants is required; the DB-driven label (`"Chegina GLOL40 — MB"`) already makes the origin obvious to the operator.

## Non-goals

- **Multi-hop aliases** (A→B→C). One hop only. Alias resolution does not recurse.
- **Cyclic aliases**. If admin adds both (A→B) and (B→A), each side surfaces the other's variants independently; no traversal loop.
- **Bulk-copy / one-shot migration** of variants between products. Alias stays live; it's a runtime lookup, not a data copy.
- **Auto-populate missing measurements**. If GLOL40 cert expects a param K40GLOL batch doesn't measure, the cert renders with an empty row. Matches existing external-lab behavior.
- **Visual distinction of aliased variants in the picker**. User explicitly preferred the flat list; the DB label already includes the product name.
- **Per-variant granularity**. The alias applies at product level — a K40GLOL→GLOL40 alias surfaces ALL GLOL40 variants, not a selected subset.
- **Cert archive retroactive relabeling**. Already-issued swiadectwa keep their original `produkt` column; the new metadata field is forward-only.

## Architecture

**One-liner:** new `cert_alias` table maps `source_produkt → target_produkt`; `GET /api/cert/templates` returns a union; `POST /api/cert/generate` accepts an optional `target_produkt`; admin UI lives in `/admin/wzory-cert`.

### Decision boundary

- **Branding source** (display_name, spec_number, opinion_pl/en, RSPO flags, variant label, cert_requirement per row) = `target_produkt` — what the cert says about itself.
- **Data source** (wyniki_flat, nr_partii, dt_start, laborant who issued) = `source batch` — what the cert reports about this production run.

Parameter matching is kod-based via the existing `build_context` lookup (`r["kod"] in wyniki_flat`). Kod mismatches yield empty rows — handled the same way as external-lab params today.

## Components

### 1. Schema

New table in `init_mbr_tables` (idempotent; `CREATE TABLE IF NOT EXISTS`):

```sql
CREATE TABLE IF NOT EXISTS cert_alias (
    source_produkt TEXT NOT NULL,
    target_produkt TEXT NOT NULL,
    PRIMARY KEY (source_produkt, target_produkt)
);
```

No FK to `produkty` — `produkty` is an advisory table and some cert-persona rows may not always be there. Application-level validation catches typos.

### 2. Backend — alias CRUD

New admin-only endpoints in `mbr/certs/routes.py`:

- `GET /api/cert/aliases` → list `[{source_produkt, target_produkt}, ...]`.
- `POST /api/cert/aliases` body `{source_produkt, target_produkt}`:
  - Reject `source == target` → 400.
  - Reject if `target_produkt` not present in `produkty` → 404.
  - `INSERT OR IGNORE` — idempotent → 200.
- `DELETE /api/cert/aliases/<source_produkt>/<target_produkt>` — idempotent → 200 (even if the row didn't exist).

Decorator: `@role_required("admin")`.

### 3. Backend — variant picker union

Modify `GET /api/cert/templates?produkt=X` in `mbr/certs/routes.py::api_cert_templates`:

```python
# Pseudocode of the new behavior
variants = get_variants(produkt)        # existing — X's own variants
for alias_target in db.execute(
    "SELECT target_produkt FROM cert_alias WHERE source_produkt=?", (produkt,)
).fetchall():
    variants += get_variants(alias_target["target_produkt"])
# Each returned item now includes "owner_produkt" so the client knows
# which product owns the variant (used by doGenerateCert).
```

Extend `get_variants(produkt)` in `mbr/certs/generator.py` to include `"owner_produkt": produkt` on each returned dict (so the union function doesn't need to post-process).

### 4. Backend — generate routing

Modify `POST /api/cert/generate` in `mbr/certs/routes.py::api_cert_generate`:

```python
# New optional field in the request body
target_produkt = data.get("target_produkt") or ebr["produkt"]

# Validate alias relationship
if target_produkt != ebr["produkt"]:
    alias_ok = db.execute(
        "SELECT 1 FROM cert_alias WHERE source_produkt=? AND target_produkt=?",
        (ebr["produkt"], target_produkt),
    ).fetchone()
    if not alias_ok:
        return jsonify({"ok": False,
                        "error": f"no cert alias configured: "
                                 f"{ebr['produkt']}→{target_produkt}"}), 400

# Pass target_produkt to the generator
pdf_bytes = generate_certificate_pdf(
    target_produkt, variant_id, ebr["nr_partii"], ebr["dt_start"],
    wyniki_flat, extra_fields, wystawil=wystawil,
)
```

`build_context` needs no changes — it already scopes everything to the `produkt` argument. Passing `target_produkt` just means it reads cert config from there.

### 5. Backend — archive

`create_swiadectwo` currently stores `produkt` (= ebr.produkt) on the `swiadectwa` row. Add a nullable `target_produkt TEXT` column so regeneration from history can reconstruct the correct branding.

Idempotent migration in `init_mbr_tables`:
```python
try:
    db.execute("ALTER TABLE swiadectwa ADD COLUMN target_produkt TEXT")
    db.commit()
except Exception:
    pass  # column already exists
```

Populate `target_produkt` on insert when it differs from `ebr.produkt`; leave NULL for own-product certs (backward compat).

### 6. Frontend — variant picker

In `mbr/templates/laborant/_fast_entry_content.html::loadCompletedCerts` and `doGenerateCert`:

- Render each variant using the DB `label` field as-is — no new badges/sections (user picked option A: flat list).
- In the POST body, include `target_produkt: v.owner_produkt`.

```javascript
// doGenerateCert payload (add the field)
fetch('/api/cert/generate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        ebr_id: ebrId,
        variant_id: variantId,
        target_produkt: ownerProdukt,  // NEW
        extra_fields: extraFields,
        wystawil: wystawil,
    }),
})
```

### 7. Frontend — admin UI

In `mbr/templates/admin/wzory_cert.html`, add a new section "Aliasy cert":

- Table listing existing aliases: columns `Produkt źródłowy`, `Produkt docelowy`, `Usuń`.
- Form to add: two `<select>` elements populated from the product list. The admin `/admin/wzory-cert` page already renders a product selector elsewhere in the file — reuse that same source (likely the Jinja-rendered `{{ produkty }}` context variable or an existing `/api/parametry/produkty-list` endpoint; confirm which pattern the file uses and copy it). No new backend endpoint for the product list is required.
- On submit → POST `/api/cert/aliases` → on success, re-render the list.

## Data flow

See Section 2 of the brainstorming — summarized: admin adds alias → laborant sees union → picks GLOL40 variant → backend validates + calls generate with `target_produkt=GLOL40` → cert renders GLOL40 branding with K40GLOL batch's measurements.

## Error handling

| Condition | Response |
|---|---|
| `POST /api/cert/generate` with `target_produkt` ≠ ebr.produkt and no alias row | HTTP 400 `"no cert alias configured: <source>→<target>"` |
| `POST /api/cert/generate` without `target_produkt` | Defaults to ebr.produkt (backward compat; existing tests continue to pass) |
| `POST /api/cert/aliases` with `source_produkt == target_produkt` | HTTP 400 `"self-alias not allowed"` |
| `POST /api/cert/aliases` with target not in `produkty` | HTTP 404 `"target produkt not found"` |
| `POST /api/cert/aliases` duplicate | HTTP 200 idempotent (INSERT OR IGNORE) |
| `DELETE /api/cert/aliases/<s>/<t>` on non-existing alias | HTTP 200 idempotent |
| Admin changes cert config on `Chegina_GLOL40` | Next K40GLOL-issued GLOL40 cert reflects the change immediately (no data duplication) |
| Admin deletes the alias after certs have been issued | Archive rows retain their `produkt` and `target_produkt`. Regeneration still works because metadata is preserved per-row. |
| Schema migration re-run | Idempotent |

## Testing

**New test files:**

1. `tests/test_cert_alias_migration.py` — `cert_alias` table + `swiadectwa.target_produkt` column created idempotently.

2. `tests/test_cert_alias_api.py`:
   - POST alias → persists; GET returns it.
   - POST self-alias → 400.
   - POST target not in produkty → 404.
   - POST duplicate → 200 idempotent (row count stays 1).
   - DELETE existing → removes.
   - DELETE non-existing → 200 (no-op).
   - Non-admin role → 403.

3. `tests/test_cert_templates_with_alias.py`:
   - Product with no alias → `/api/cert/templates?produkt=X` returns only X's variants; each has `owner_produkt=X`.
   - Product with alias X→Y → returns X's variants + Y's variants; `owner_produkt` is set correctly per entry.

4. `tests/test_cert_generate_with_alias.py`:
   - Valid alias, generate with `target_produkt=Y` → context uses Y's `display_name`, `spec_number`, param rows; `wyniki_flat` keys come from X's batch.
   - `target_produkt=Y` without alias → 400.
   - Omit `target_produkt` → falls back to ebr.produkt (backward compat).

**Manual smoke (post-deploy):**

5. Admin opens `/admin/wzory-cert`, adds `Chegina_K40GLOL → Chegina_GLOL40`.
6. Laborant opens a K40GLOL batch → variant picker shows 5 K40GLOL variants + 4 GLOL40 variants (labels include product name).
7. Pick `Chegina GLOL40 — MB` → PDF generates with GLOL40 display_name and K40GLOL batch's nr_partii/measurements.
8. Admin deletes alias → laborant refreshes picker → sees only 5 K40GLOL variants.

## Open questions

None. All decisions locked in via brainstorming session 2026-04-19.

## References

- Brainstorming session: conversation 2026-04-19
- Cert generation pipeline: `mbr/certs/generator.py::build_context` (line 193+)
- Variant picker: `mbr/templates/laborant/_fast_entry_content.html::loadCompletedCerts`
- Admin cert editor: `mbr/templates/admin/wzory_cert.html`
- Related spec: `docs/superpowers/specs/2026-04-19-external-lab-params-design.md` (shares grupa-agnostic + kod-match patterns)
