# Dead Code Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find and remove all dead code (unused modules, functions, imports, templates, scripts) from the LIMS codebase.

**Architecture:** Scan in parallel by area — each task is an independent investigation by a subagent. Each subagent produces a report of dead code found. After all reports are collected, a final cleanup task removes confirmed dead code in one sweep.

**Tech Stack:** Python (grep, AST analysis), Jinja templates, JS

---

## Phase 1: Investigation (parallel subagents)

### Task 1: Vestigial top-level modules in `mbr/`

**Context:** Several modules at `mbr/` root appear to be old versions that were refactored into blueprint subdirectories. Check if they are still imported/used anywhere.

**Suspects:**
- `mbr/etapy_config.py` — possibly replaced by `mbr/etapy/config.py`
- `mbr/etapy_models.py` — possibly replaced by `mbr/etapy/models.py`
- `mbr/parametry_registry.py` — possibly replaced by `mbr/parametry/registry.py`
- `mbr/cert_gen.py` (277 lines) — possibly replaced by `mbr/certs/generator.py`
- `mbr/pdf_gen.py` — possibly replaced by `mbr/certs/generator.py`
- `mbr/seed_parametry.py` — possibly replaced by `mbr/parametry/seed.py`
- `mbr/seed_mbr.py` (1143 lines) — check if still used or replaced by pipeline setup
- `mbr/test_workflow.py` — test file inside source tree, not in `tests/`

- [ ] **Step 1:** For each suspect file, run `grep -r "from mbr.etapy_config\|import etapy_config" mbr/ tests/ scripts/ *.py` (adapt for each module name). Also check `mbr/app.py` imports and blueprint registrations.
- [ ] **Step 2:** For files that ARE imported somewhere, check if the import is itself dead (e.g. imported in another dead file).
- [ ] **Step 3:** Read each suspect file briefly to confirm it's a duplicate of the blueprint version, not a different module with same name.
- [ ] **Step 4:** Produce report: `DEAD: filename (reason)` or `ALIVE: filename (used by X)`.

---

### Task 2: Unused functions in `mbr/models.py` (1430 lines)

**Context:** `mbr/models.py` is the largest file. It contains `init_mbr_tables()` plus many helper functions. Some may be vestigial after refactoring into blueprint `models.py` files.

- [ ] **Step 1:** Extract all `def function_name(` from `mbr/models.py`.
- [ ] **Step 2:** For each function, grep the entire codebase (`mbr/`, `tests/`, `scripts/`, `*.py`, `mbr/templates/`) for usage (excluding the definition itself).
- [ ] **Step 3:** Pay special attention to functions called from Jinja templates (e.g. context processors) — grep `.html` files too.
- [ ] **Step 4:** Check `init_mbr_tables()` for table CREATE statements that might be for tables no longer used.
- [ ] **Step 5:** Produce report: list of unused functions with line numbers.

---

### Task 3: Unused functions in blueprint `models.py` files

**Context:** Each blueprint has its own `models.py`. Check for unused functions in:
- `mbr/laborant/models.py` (1025 lines)
- `mbr/etapy/models.py` (282 lines)
- `mbr/registry/models.py`
- `mbr/workers/models.py`
- `mbr/auth/models.py`
- `mbr/technolog/models.py`
- `mbr/zbiorniki/models.py`
- `mbr/certs/models.py`
- `mbr/certs/mappings.py` (755 lines — large, may have dead mappings)

- [ ] **Step 1:** For each file, extract all `def function_name(` definitions.
- [ ] **Step 2:** Grep the entire codebase for each function name (excluding definition).
- [ ] **Step 3:** Check template files for function calls via context processors or Jinja filters.
- [ ] **Step 4:** Produce report per file: unused functions with line numbers.

---

### Task 4: Unused functions in `mbr/pipeline/models.py` and `mbr/pipeline/adapter.py`

**Context:** Pipeline module (1147 + 361 lines) was built incrementally. Some CRUD functions may never be called.

- [ ] **Step 1:** Extract all `def` from `mbr/pipeline/models.py` and `mbr/pipeline/adapter.py`.
- [ ] **Step 2:** Grep for each function across `mbr/`, `tests/`, `scripts/`.
- [ ] **Step 3:** Check `mbr/pipeline/lab_routes.py` and `mbr/pipeline/routes.py` for route handlers that may be dead (no frontend calls them).
- [ ] **Step 4:** For route handlers, grep templates and JS for the URL pattern (e.g. `/api/pipeline/...`).
- [ ] **Step 5:** Produce report.

---

### Task 5: Unused routes across all blueprints

**Context:** Routes may have been added but never called from frontend. Check all `@bp.route(...)` handlers.

**Blueprints to scan:**
- `mbr/auth/routes.py`
- `mbr/workers/routes.py`
- `mbr/technolog/routes.py`
- `mbr/laborant/routes.py`
- `mbr/certs/routes.py`
- `mbr/registry/routes.py`
- `mbr/etapy/routes.py`
- `mbr/parametry/routes.py`
- `mbr/zbiorniki/routes.py`
- `mbr/paliwo/routes.py`
- `mbr/admin/routes.py`, `mbr/admin/audit_routes.py`

- [ ] **Step 1:** Extract all route paths (URL patterns) from each file.
- [ ] **Step 2:** For each route, grep all `.html` templates and `.js` files for the URL pattern.
- [ ] **Step 3:** Also check Python code for `url_for('blueprint.function')` calls.
- [ ] **Step 4:** Routes only called from migration scripts (one-time use) should be flagged separately.
- [ ] **Step 5:** Produce report: unused routes with file and line number.

---

### Task 6: Dead templates and template partials

**Context:** Jinja templates in `mbr/templates/`. Some may no longer be rendered by any route.

- [ ] **Step 1:** List all `.html` files in `mbr/templates/` recursively.
- [ ] **Step 2:** For each template, grep Python routes for `render_template('filename')` or `render_template("filename")`.
- [ ] **Step 3:** Check for `{% include %}` and `{% extends %}` references from other templates.
- [ ] **Step 4:** Check for `{% from "..." import ... %}` macro imports.
- [ ] **Step 5:** Produce report: unreferenced templates.

---

### Task 7: Dead root-level scripts

**Context:** Many `*.py` scripts in repo root and `scripts/` directory. Migration scripts are one-time use (acceptable), but some may be analysis/feature scripts that are no longer needed.

**Root scripts:** `acid_model.py`, `acid_estimation_analysis.py`, `extract_cert_params.py`, `extract_ods_params.py`, `feature_analysis.py`, `fix_cert_params.py`, `verify.py`, `train_acid_model.py`

**Scripts dir:** `scripts/backfill_*.py`, `scripts/migrate_*.py`, `scripts/setup_*.py`, `scripts/deploy_*.py`

- [ ] **Step 1:** For each root script, check if it's imported anywhere or referenced in any docs/config.
- [ ] **Step 2:** Check git log for last modification date — scripts not touched in months that aren't migrations are likely dead.
- [ ] **Step 3:** Read the docstring/header of each script to understand purpose.
- [ ] **Step 4:** Classify each as: `MIGRATION` (keep), `ACTIVE TOOL` (keep), `DEAD` (remove), `ARCHIVE` (move to archive).
- [ ] **Step 5:** Produce report.

---

### Task 8: Unused imports, dead CSS, dead JS

**Context:** Quick scan for low-hanging fruit.

- [ ] **Step 1:** Run `python3 -c "import py_compile; py_compile.compile('mbr/app.py')"` etc. to check for syntax errors that might indicate dead files.
- [ ] **Step 2:** Grep for `import` statements in Python files where the imported name is never used in that file.
- [ ] **Step 3:** In `mbr/static/style.css` — look for CSS classes not referenced in any template (sample check for suspicious class prefixes).
- [ ] **Step 4:** Check `mbr/static/*.js` files — are they all loaded? Are functions in them called from templates?
- [ ] **Step 5:** Produce report.

---

### Task 9: Dead database tables and columns

**Context:** `init_mbr_tables()` in `mbr/models.py` creates many tables. Some may be vestigial (v3 leftovers, replaced by pipeline tables, etc.).

- [ ] **Step 1:** Extract all `CREATE TABLE` statements from `mbr/models.py` and blueprint `models.py` files.
- [ ] **Step 2:** For each table name, grep Python code for SQL queries using that table.
- [ ] **Step 3:** Tables only referenced in `CREATE TABLE` and never queried/inserted are dead.
- [ ] **Step 4:** Check for columns in active tables that are never read or written (sample the largest tables).
- [ ] **Step 5:** Produce report: dead tables, potentially dead columns.

---

## Phase 2: Cleanup (sequential, after all reports)

### Task 10: Review and execute cleanup

- [ ] **Step 1:** Collect all reports from Tasks 1-9.
- [ ] **Step 2:** Cross-reference findings — a function flagged dead in Task 3 might be the only caller of a function flagged alive in Task 2.
- [ ] **Step 3:** Create a consolidated delete list, categorized by confidence:
  - **HIGH:** file/function has zero references anywhere
  - **MEDIUM:** file/function referenced only from other dead code
  - **LOW:** file/function might be called dynamically (getattr, template context)
- [ ] **Step 4:** Delete HIGH confidence dead code first, run `pytest` after each batch.
- [ ] **Step 5:** Delete MEDIUM confidence, run `pytest`.
- [ ] **Step 6:** Flag LOW confidence items with `# TODO: verify if dead` comments.
- [ ] **Step 7:** Final `pytest` run — all tests must pass.
- [ ] **Step 8:** Commit: `chore: remove dead code (modules, functions, routes, templates)`
