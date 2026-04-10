# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

LIMS / MBR–EBR web application for a chemical plant (iChegina K40GLO). Flask monolith backed by SQLite, rendering server-side Jinja templates and generating DOCX→PDF batch records and certificates of analysis (Świadectwa Jakości). Polish-language domain (produkt, szarża, laborant, technolog, etapy, parametry).

The system models the lifecycle:
- **MBR templates** (Master Batch Record) — recipe/process definition per `produkt`, versioned.
- **EBR batches** (Executed Batch Record) — a run of an MBR instance, with stage events, lab analyses, and operator inputs.
- **Świadectwa** (certificates of analysis) — generated from EBR results + per-product DOCX templates.

## Running

```bash
# Dev server (Flask, debug, port 5001)
python -m mbr.app

# Or via gunicorn (production setup, as in deploy/lims.service)
gunicorn --bind 127.0.0.1:5001 --workers 2 --timeout 120 mbr.app:app

# Install deps
pip install -r mbr/requirements.txt
```

Environment: `MBR_SECRET_KEY` (Flask session key). Default dev value is hardcoded — do not rely on it in prod.

SQLite DB lives at `data/batch_db.sqlite` (see `mbr/db.py`). Tables are auto-created by `init_mbr_tables()` on app startup. Note: `mbr/models.py` defines a second path `batch_db_v4.sqlite` which is vestigial — the active path is the one in `mbr/db.py`.

PDF rendering requires **Gotenberg** running on `localhost:3000` (DOCX→PDF conversion). In production it runs as a Docker container via `deploy/gotenberg.service`. Without it, cert/report PDF endpoints fail.

## Tests

```bash
pytest                          # all tests
pytest tests/test_certs.py      # single file
pytest tests/test_certs.py::test_name  # single test
```

Tests use in-memory SQLite fixtures and `init_mbr_tables()` directly — no running server required. There is no `pytest.ini`/`pyproject.toml`; pytest auto-discovers `tests/`.

## Architecture

### Flask app factory — `mbr/app.py`

`create_app()` wires the app, registers a dozen blueprints, and runs `init_mbr_tables()` inside an app context on startup. It also back-fills `metoda_id` for parameters seeded before `metody_miareczkowe` existed — that startup fixup is load-bearing; don't remove it without a migration.

Cache-Control headers are set in an `after_request` hook: HTML/JSON always `no-store`, static assets `max-age=1 year immutable` (cache-bust via `?v=` query string in templates).

### Blueprints (each a self-contained module under `mbr/`)

| Blueprint | Role |
|---|---|
| `auth` | Login/logout, bcrypt password hashes, session cookie |
| `workers` | User/worker CRUD (admin) |
| `technolog` | MBR template authoring (recipe, stages, param specs) |
| `laborant` | EBR execution: stage events, lab analyses, workflows for laborant / laborant_kj / laborant_coa roles |
| `certs` | Certificate of analysis generator (DOCX templates + docxtpl + Gotenberg) |
| `paliwo` | Fuel-specific batch/report flow |
| `registry` | Registry/lookup data |
| `etapy` | Stage catalog + per-product stage configuration |
| `parametry` | Analytical parameter registry + titration methods |
| `zbiorniki` | Storage tanks |
| `admin` | Admin panel (feedback export, settings) |

Standard blueprint layout: `__init__.py` (bp object), `routes.py` (Flask handlers), `models.py` (SQL helpers — plain `sqlite3`, no ORM). Shared helpers in `mbr/shared/` (`decorators.py` has `login_required` / `role_required(*roles)`, `filters.py` Jinja filters, `context.py` context processor).

### Roles

Five roles, enforced via `@role_required`: `technolog`, `laborant`, `laborant_kj`, `laborant_coa`, `admin`. They map to distinct UI flows — a route's permitted roles are the ground truth, not the folder name.

### Certificates (`mbr/certs/`)

- Per-product DOCX templates under `mbr/templates/` (e.g. `cert_master_template.docx`, `paliwo_master*.docx`).
- Variant / field configuration in `mbr/cert_config.json` — the SSOT for which parameters appear on which cert variant. Migration/deploy scripts live in `scripts/migrate_cert_config.py` and `scripts/deploy_cert_ssot.py`.
- `generator.py` fills the DOCX via `docxtpl`, then POSTs to Gotenberg for PDF conversion. `build_preview_context()` powers the live editor preview.
- Cert PDF naming convention: `Świadectwo_<product>_...` — see recent commit `746f860`.

### Database

Single SQLite file, FK enforcement on (`PRAGMA foreign_keys=ON`). Schema in `schema_v4.sql` + `init_mbr_tables()` in `mbr/models.py` and each blueprint's `models.py`. Migrations are ad-hoc Python scripts in repo root (`migrate_v4.py`, `migrate_ocr_to_lims.py`, `apply_cert_extraction.py`, etc.) — there is no migration framework; they are run manually once per deploy.

### Companion apps

- `coa_app/` — standalone PyInstaller-packaged Windows COA (certificate of analysis) viewer. Separate `requirements.txt`, separate `app.py`. Not part of the main Flask app.
- `cert-watchdog/` — PowerShell watchdog that monitors cert output directory on a Windows client.

### Deployment

`deploy/` contains systemd units for a Linux box (`lims.service`, `gotenberg.service`, `auto-deploy.service`+timer, `kiosk.service` for a browser kiosk) and an nginx reverse-proxy config. `auto-deploy.sh` pulls from git on a timer.

## Conventions

- All domain vocabulary is Polish. Route paths, DB columns, and variables mix Polish (`produkt`, `szarża`, `etapy_json`) with English technical terms — follow the existing style for new code in a blueprint.
- Raw `sqlite3` everywhere, no SQLAlchemy. Queries use `?` placeholders and `Row` factory; prefer adding helpers to the blueprint's `models.py` over inlining SQL in routes.
- JSON blobs in columns (`etapy_json`, `surowce_json`, `parametry_lab`, `przepompowanie_json`) are load-bearing — treat them as schemas even though SQLite won't enforce them.
- Static-asset cache busting: append `?v=<something>` to URLs in templates; the global `Cache-Control: immutable` rule relies on it.
