# Acid Model — Living Retraining Pipeline for Chegina K7

Status: Draft for user review
Date: 2026-04-21
Scope: Chegina K7 only (other K40 variants out of scope for this iteration)

## Motivation

`acid_model.py` currently runs ad-hoc and produces an HTML report. The K7
branch of that script fits OLS on `dmapa_zwrotna_per_ton` and reports
LOO-CV MAE ≈ 5.82 kg. The model is not served anywhere — laborant types
acid doses by hand at the `standaryzacja` stage.

Three realities call for change:

1. **Data accumulates.** Roughly 50 K7 batches/month, each with 3 stages
   of structured data (strona1, proces, analiza końcowa). The static
   trainer only reads `data/verified/` — a manually curated snapshot —
   and doesn't learn from new production batches automatically.

2. **Raw-material lot structure is known to matter but unexploited.**
   Operator can reliably assert "the last 3–5 K7 batches used the same
   DMAPA lot." Current model treats every batch as independent, losing
   that grouping signal.

3. **No feedback loop.** Operator never sees the model's suggestion in
   the UI, so we can't measure "would they have accepted the prediction"
   and we can't retrain on post-deployment observations.

## Goals

- **Auto-retrain weekly** (systemd timer, Sunday 02:00 UTC). New
  candidate model is promoted to champion only if it doesn't regress.
- **Serve acid-dose suggestion in the laborant UI** at the standaryzacja
  stage with the current "auto-fill + badge" pattern. Audit every
  acceptance / override for future training.
- **Use raw-material lot as a grouping variable** via `statsmodels.MixedLM`
  (random effect on lot). Handles new lots gracefully (falls back to
  population mean).
- **Admin CRUD for raw-material lots** with date-range tracking. Future
  v2: watchdog on the Excel registry file that auto-ingests new lots.
- **Safety gate**: reject new model if LOO-CV MAE regresses >10% vs.
  champion. Manual force-promote available to admin.
- **K7 only.** Other products keep the static `acid_model.py` pipeline
  until this system proves stable.

## Non-goals

- Cross-product generalization (K40GL, K40GLO, K40GLOL stay with the
  old trainer for now).
- Real-time model retraining on every batch completion. Weekly cadence
  is the operational contract.
- Feature selection via automated search (Lasso, stepwise, etc.). We
  hand-pick the feature set up front and let LOO-CV tell us how it
  performs.
- Web UI for inspecting model internals beyond a basic
  `/admin/acid-model` dashboard (MAE trend, last retrain log, force-promote
  button).
- Replacement of `acid_model.py` for the other three products.

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│ 1. Feature store                                               │
│    scripts/build_acid_feature_table.py                         │
│    output: data/models/k7/features.parquet                     │
│    row = 1 completed K7 batch; columns = features + target     │
└────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────────┐
│ 2. Lot registry                                                │
│    table raw_material_lots (SQLite)                            │
│    /admin/surowce-partie — CRUD                                │
│    (v2) cert-watchdog-style Excel watcher                      │
└────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────────┐
│ 3. Trainer                                                     │
│    scripts/retrain_acid_model.py --product K7                  │
│    systemd: deploy/acid-retrain.timer (Sun 02:00 UTC)          │
│    output: data/models/k7/{timestamp}.pkl + metadata.json      │
│    promotes → data/models/k7/champion.pkl if MAE ≤ 110% prev   │
└────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────────┐
│ 4. Serving                                                     │
│    GET /api/model/acid-estimate?ebr_id=N                       │
│    → {predicted_kg, ci_lo, ci_hi, model_version, model_mae}    │
│    in-memory cache; reload when champion.pkl mtime changes     │
└────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────────┐
│ 5. UI                                                          │
│    laborant/_fast_entry_content.html — standaryzacja pole      │
│    "kwas cytrynowy" auto-fill z modelu + "Model vN ±X kg"      │
│    audit: model.suggestion_accepted / model.suggestion_overridden │
└────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────────┐
│ 6. Monitoring                                                  │
│    table acid_predictions — prediction vs. actual per batch    │
│    /admin/acid-model — MAE ostatnich 30 dni, lista retrainów   │
└────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Feature store — `scripts/build_acid_feature_table.py`

Joins the three batch stages into one row per completed K7 batch.
Output: `data/models/k7/features.parquet` (Parquet for typed columns
and efficient row appends). Built incrementally (only new batches since
last run), full rebuild via `--rebuild` flag.

Columns (schema v1):

| Column                   | Source                                       | Notes                      |
|--------------------------|----------------------------------------------|----------------------------|
| `ebr_id`                 | `ebr_batches.ebr_id`                         | PK                         |
| `nr_partii`              | `ebr_batches.nr_partii`                      | Human-readable             |
| `dt_start`               | `ebr_batches.dt_start`                       | Batch start datetime       |
| `wielkosc_kg`            | strona1                                       | Batch size                 |
| `tons`                   | `wielkosc_kg / 1000`                         | Derived                    |
| `dmapa_zwrotna_kg`       | strona1.surowce (kod_surowca='dmapa_zwrotna')| Raw material loaded        |
| `dmapa_zwrotna_per_ton`  | Derived                                      | Primary feature            |
| `ph_utl`                 | proces.etapy.utlenienie → last `ph_10proc`   | Stage 2 measurement        |
| `acid_kg`                | strona1.standaryzowanie (kod='kw_cytrynowy') | **Target**                 |
| `ph_koniec`              | analiza_koncowa.ph_10proc                    | Validation                 |
| `delta_ph`               | `ph_utl - ph_koniec`                         | Derived                    |
| `buffer_cap`             | `(acid_kg / tons) / delta_ph`                | Derived target             |
| `lot_dmapa_zwrotna`      | lookup from `raw_material_lots` by dt_start  | Grouping var               |
| `source`                 | "verified" | "live_prod"                      | Trainer filters             |

Batches where any of `ph_utl`, `acid_kg`, `ph_koniec` is missing or
where `delta_ph ≤ 0.5` are excluded (filter matches the existing
`acid_model.py:build_dataset`). Status `status='completed'` required.

### 2. Lot registry

New table `raw_material_lots`:

```sql
CREATE TABLE raw_material_lots (
    id            INTEGER PRIMARY KEY,
    surowiec_kod  TEXT NOT NULL,       -- e.g. 'dmapa_zwrotna', 'koh'
    lot_number    TEXT NOT NULL,       -- supplier lot id
    dt_dostawy    TEXT NOT NULL,       -- ISO date
    dt_wyczerpania TEXT,               -- null if still in use
    uwagi         TEXT,
    UNIQUE (surowiec_kod, lot_number)
);
```

Lot-to-batch linkage is **temporal**: for each batch, for each
tracked raw material, pick the lot with
`max(dt_dostawy) WHERE dt_dostawy <= batch.dt_start`. If no lot record
exists, `lot_id` is NULL and the model treats this batch as having an
"unknown" lot (participates in the fixed part of the mixed model, no
random-effect contribution).

**v1 scope: only `surowiec_kod='dmapa_zwrotna'` is tracked.** Other
raw materials can be added later without schema change.

Admin UI: new route `/admin/surowce-partie` — simple CRUD form
(surowiec dropdown → lot_number input → dt_dostawy picker). Audit
events `raw_material_lot.created` / `raw_material_lot.updated` /
`raw_material_lot.deleted` via existing `audit.log_event`.

v2 Excel watcher deferred: same file layout as `cert-watchdog/`
(PowerShell on Windows kiosk) polls a shared xlsx, calls a new
`POST /api/surowce-partie/ingest` endpoint with parsed rows. Not in
this iteration.

### 3. Trainer — `scripts/retrain_acid_model.py`

Invocation: `python scripts/retrain_acid_model.py --product K7 [--force-promote]`.

Steps:

1. Rebuild feature table from DB (incremental).
2. Fit `statsmodels.MixedLM`:
   ```python
   formula = "buffer_cap ~ dmapa_zwrotna_per_ton + ph_utl + tons"
   model = MixedLM.from_formula(
       formula,
       groups="lot_dmapa_zwrotna",
       re_formula="~1",  # random intercept per lot
       data=df,
   ).fit()
   ```
3. LOO-CV on non-null-lot rows → compute `mae`, `mape`, `n_obs`,
   `n_lots`.
4. Load previous `data/models/k7/champion.pkl` + `champion_metadata.json`.
5. If `new.mae <= champion.mae * 1.10` OR no champion exists OR
   `--force-promote`: write new pickle, write new metadata, atomically
   replace `champion.pkl` symlink.
6. Write `data/models/k7/training_log.jsonl` entry — timestamp,
   decision (`promoted`|`rejected`|`forced`), MAE, MAPE, n_obs, diff
   vs. champion.
7. Emit audit event `model.retrained` with the log entry payload.

systemd units in `deploy/`:

```
deploy/acid-retrain.service   (Type=oneshot, ExecStart=/opt/lims/venv/bin/python scripts/retrain_acid_model.py --product K7)
deploy/acid-retrain.timer     (OnCalendar=Sun *-*-* 02:00:00 UTC, Persistent=true)
```

Installed alongside `lims.service` via one-time SSH setup (analogous
to `lims-backup.timer`).

### 4. Serving — `GET /api/model/acid-estimate`

New Flask blueprint `mbr/acid_model/`:
- `__init__.py` — bp definition
- `routes.py` — the endpoint
- `predictor.py` — model load/predict logic (lazy-loaded, reloaded on
  `champion.pkl` mtime change)
- `models.py` — `acid_predictions` table DDL + helpers

Endpoint contract:

```
GET /api/model/acid-estimate?ebr_id=<int>

200:
{
  "predicted_acid_kg":  87.3,
  "ci_lo":              81.1,     // 68% CI from model.conf_int()
  "ci_hi":              93.5,
  "model_version":      "2026-04-27T02:00:04",
  "model_mae_kg":       5.21,
  "lot_in_model":       true,     // false if this batch's lot has no training data
  "features_missing":   []        // e.g. ["ph_utl"] — predict still succeeds with fixed-effect fallback
}
422: features impossible to gather (e.g. batch doesn't exist, wrong product)
503: no champion model on disk
```

The endpoint pulls features from the **same** DB queries the feature
store uses (extracted into `predictor._gather_features(ebr_id)`), so
trainer and server see identical feature values.

Caching: on first request after server start, the Flask process reads
`champion.pkl` into a module-level variable. Subsequent requests check
the file's `mtime`; if changed, reload. No manual reload endpoint needed
(deploy-level restart of lims.service also flushes the cache).

### 5. UI — laborant hero

Located at the `standaryzacja` stage render, where the
`kwas_cytrynowy` input currently exists. Behavior change:

- On hero render, if the input's value is empty AND the field is in
  the user-editable state, the JS calls `/api/model/acid-estimate` for
  the current `ebr_id`. On success, the input is auto-filled with
  `predicted_acid_kg.toFixed(0)` (kg, integer) and a small badge
  appears to the right: `Model v2026-04-27 ±5.2 kg`.
- The input retains a new data attribute `data-model-suggestion`
  storing the raw predicted value.
- On `onblur`, if the user kept the value equal to the suggestion
  (within 0.5 kg tolerance for rounding), the save path logs an audit
  event `model.acid_suggestion_accepted` with `{predicted_kg,
  accepted_kg, model_version}`. If the user changed it, the event is
  `model.acid_suggestion_overridden` with `{predicted_kg, actual_kg,
  delta_kg, model_version}`.
- Visual: badge styled like the existing `.type-tag` but with a new
  `.t-model` class — light-blue background, tooltip on hover shows
  full metadata.
- No auto-fill if API returns 422/503; input stays empty and the badge
  reads "Model niedostępny".

### 6. Monitoring — `/admin/acid-model`

New table:

```sql
CREATE TABLE acid_predictions (
    id             INTEGER PRIMARY KEY,
    ebr_id         INTEGER NOT NULL,
    model_version  TEXT NOT NULL,
    predicted_kg   REAL NOT NULL,
    ci_lo          REAL,
    ci_hi          REAL,
    actual_kg      REAL,        -- filled in when batch completes
    residual_kg    REAL,        -- actual - predicted (filled on completion)
    predicted_at   TEXT NOT NULL,
    FOREIGN KEY (ebr_id) REFERENCES ebr_batches(ebr_id)
);
```

Written on every serving call (`predicted_at` = request time). Updated
at `/laborant/ebr/<id>/complete` (hook into the existing completion
path): if this batch has a prediction row, fill `actual_kg` from the
final acid_kg in standaryzowanie, compute `residual_kg`.

Admin dashboard `/admin/acid-model`:
- Card 1: current champion — version, MAE, date promoted, n_obs_trained.
- Card 2: MAE rolling 30 days (live residuals from `acid_predictions`).
  Sparkline plot.
- Card 3: last 10 retrain attempts (from `training_log.jsonl`) —
  decision column, MAE, MAE delta.
- Button: "Wymuś promocję" — runs `scripts/retrain_acid_model.py
  --force-promote` via `sudo systemctl start acid-retrain.service
  --runtime-var=FORCE=1` (or simpler: Flask endpoint `POST
  /api/model/acid-estimate/force-promote` that invokes the script
  in-process).
- Table: top 10 worst predictions last 30 days (residual, batch, lot).
  Diagnostic tool for operator intervention.

## Data flow

1. Operator completes K7 batch at standaryzacja: laborant enters
   `kwas_kg`, saves. Save path:
   - `acid_predictions.actual_kg` filled if prediction row exists.
   - Audit event logged.
2. Weekly cron Sun 02:00 → `scripts/retrain_acid_model.py`:
   - Rebuild feature table (incremental append of new completed batches).
   - Fit MixedLM.
   - Evaluate LOO-CV.
   - Promote or reject.
3. Next operator session for a K7 batch at standaryzacja:
   - Hero render calls `/api/model/acid-estimate`.
   - Server loads champion (cached), computes prediction, writes
     `acid_predictions` row.
   - Laborant sees auto-filled value.

## Error handling

- **No champion.pkl:** serving returns 503. UI shows "Model niedostępny".
  Never blocks operator; they enter kwas_kg manually.
- **Feature gathering fails (missing ph_utl, batch wrong product):**
  server returns 422 with a reason. UI shows "Model niedostępny".
- **Training fails (MixedLM non-convergence, data too sparse):** trainer
  logs failure in `training_log.jsonl`, emits audit event, exits non-zero.
  systemd picks up the failure; admin sees next-time it opens the
  dashboard or via an email if configured. Champion is NOT replaced.
- **Trainer promotion gated:** if `new.mae > champion.mae * 1.10`,
  rejection is logged; champion remains. Operator can manually inspect
  and force-promote if justified (e.g., a data-quality fix that caused
  a temporary MAE spike).

## Testing

`tests/test_acid_model_pipeline.py`:
- `build_feature_table` produces expected rows given a seeded DB.
- `raw_material_lots` temporal lookup: given lots at 2024-01-01 and
  2024-02-15, a batch on 2024-02-10 gets the Jan lot, a batch on
  2024-03-01 gets the Feb lot.
- `retrain` promotes on fresh DB (no champion yet).
- `retrain` rejects when new MAE is >10% above champion MAE.
- `retrain` promotes on `--force-promote` even when new is worse.
- `/api/model/acid-estimate` returns correct shape given a mocked
  champion and a seeded batch.
- `/api/model/acid-estimate` returns 503 when no champion exists.
- `acid_predictions.actual_kg` is filled when `/laborant/ebr/<id>/complete`
  fires.

No integration test for the systemd timer (out-of-band).

## Risks

- **MixedLM non-convergence** on small data (<~15 batches with lots
  identified). Mitigation: trainer falls back to OLS + population mean
  if MixedLM fails, logs the fallback decision, still gates on MAE.
- **New lots with no prior data:** random-effect contribution is zero
  (population intercept). Prediction is still usable but less accurate
  until a few batches accrue. UI badge shows `lot_in_model: false` to
  signal lower confidence.
- **Model drift from batch-card entry errors.** If an operator enters
  a wildly wrong ph_utl, the feature store picks it up and trainer uses
  it. Partial mitigation via data-sanity filters in
  `build_acid_feature_table.py` (e.g. `ph_utl < 8 or ph_utl > 14` →
  excluded). Bigger fix: admin review of outliers, out of scope.
- **Post-deploy silence.** If the serving endpoint fails silently
  (e.g. champion.pkl is corrupt), laborant sees "Model niedostępny"
  and continues as today — no regression, but also no signal we've
  broken the feature. Partial fix: daily healthcheck ping from the
  retrainer that hits the endpoint; out of scope for v1.

## Rollout

1. Deploy schema migrations: `raw_material_lots`, `acid_predictions`.
2. Deploy admin UI for lot CRUD. Operator seeds current known lots.
3. Deploy feature-store script + first retrain (manually invoked). Review
   LOO-CV MAE — should be in the same ballpark as the old `acid_model.py`
   K7 MAE (~5.82kg) or better.
4. Deploy serving endpoint. Smoke-test via curl before UI change.
5. Deploy UI change (auto-fill + badge). Operator sees suggestion; can
   override at will.
6. Enable systemd timer. Next Sunday the first auto-retrain happens.
7. After 4 weeks, review `/admin/acid-model` dashboard: residuals
   stable, retrains mostly promoted (not rejected), no operator
   complaints → graduate from "experimental" to "stable."

## Open questions

None at draft time. All five critical decisions confirmed in chat
2026-04-21:

- Retrain cadence: weekly cron, Sunday 02:00 UTC.
- Lot source: admin CRUD (v1) + Excel watcher (v2 deferred).
- Model form: MixedLM random intercept per lot.
- UI: auto-fill + badge, matching existing pattern.
- Rollback: auto-reject if MAE > champion × 1.10, manual force-promote
  via admin.

## Implementation-plan note

The full scope is ~15–20 atomic tasks. Writing-plans skill should
consider splitting into two sequential plans for reviewability:

- **Plan 1 — Infrastructure and training:** `raw_material_lots` table +
  admin CRUD, feature store, trainer, systemd timer, serving endpoint.
  Terminal state: `curl /api/model/acid-estimate?ebr_id=N` returns a
  number. No UI touchpoint yet.
- **Plan 2 — UI and monitoring:** laborant hero auto-fill + badge, audit
  events, `acid_predictions` table, `/admin/acid-model` dashboard.

Both plans share this spec. Decision on split deferred to writing-plans.

## Follow-ups (explicitly deferred)

- Extend to K40GL / K40GLO / K40GLOL products (separate specs each).
- Expand tracked raw materials beyond `dmapa_zwrotna` (KOH, water, etc.).
- Excel watchdog for lot ingestion (cert-watchdog-style).
- Feature selection automation (Lasso / stepwise).
- Email/Slack alert on training failure.
- Daily healthcheck of serving endpoint.
- Admin view of per-lot residual variance (lot diagnostic table).
