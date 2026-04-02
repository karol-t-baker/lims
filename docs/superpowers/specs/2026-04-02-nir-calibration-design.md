# NIR Calibration Tool — Design Spec

## Goal

Web-based tool for building NIR spectroscopy calibration models. Import spectra + reference values, preprocess, explore with PCA, build PLS models with cross-validation. Inspired by Eigenvector Diviner but focused on MVP: import → preprocessing → PCA → PLS.

## Scope

**In scope (MVP):**
- Import: directory of CSV spectra (wavenumber, absorbance) + referencje.csv
- Preprocessing: SNV, MSC, derivatives (Savitzky-Golay), baseline, range cut, mean center
- PCA: scores, loadings, scree, Hotelling T² + Q residuals
- PLS: single target, configurable LV count, LOO/K-fold CV, RMSEC/RMSECV/R²
- Web UI with Plotly interactive charts

**Out of scope (future):**
- AutoML (brute-force preprocessing combinations)
- Variable selection (iPLS)
- Outlier removal workflow
- Ensemble models
- Model export/deployment

## Architecture

Separate project, e.g. `~/Desktop/nir-calibration/`:

```
nir-calibration/
├── app.py                  # FastAPI backend + API endpoints
├── preprocess.py           # preprocessing functions (pure numpy/scipy)
├── models.py               # PCA, PLS wrappers (scikit-learn)
├── data_loader.py          # import spectra CSV + referencje.csv
├── static/
│   └── index.html          # SPA — single file, Plotly.js, no build step
├── projects/               # user data (project directories)
│   └── example/
│       ├── widma/
│       │   ├── probka_001.csv
│       │   └── probka_002.csv
│       ├── referencje.csv
│       └── config.yaml
└── requirements.txt        # fastapi, uvicorn, scikit-learn, numpy, scipy
```

**Tech stack:**
- Backend: FastAPI (async, auto-docs at /docs)
- Frontend: single HTML + inline JS + Plotly.js (no framework, no build)
- ML: scikit-learn (PCA, PLSRegression)
- Data: numpy arrays in memory, projects as directories on disk

## Data Format

### Spectra CSV (one file = one spectrum)

Two columns: wavenumber, absorbance. No header or with header (autodetect).

```csv
4000,0.123
3998,0.125
3996,0.130
...
```

Separator autodetect: `,` / `;` / `\t`

### referencje.csv

```csv
plik,procent_sa,procent_sm,nd20
probka_001.csv,38.3,45.0,1.407
probka_002.csv,37.1,44.2,1.405
```

Column `plik` matches spectrum filename. Remaining columns are numeric targets.

### Data Loading (`data_loader.py`)

- Scan `projects/{name}/widma/*.csv`
- Parse each CSV → (wavenumbers, absorbance) arrays
- If spectra have different wavenumber ranges → interpolate to common grid
- Load `referencje.csv`, match by filename
- Samples without references: OK for PCA, excluded from PLS
- Validation: warn on different lengths, error on empty/missing files
- Output: `X` (n_samples × n_wavenumbers), `wavenumbers` (1D), `y` (dict of target_name → array), `sample_names` (list)

## Preprocessing (`preprocess.py`)

Each method is a pure function: `(X, wavenumbers, **params) → (X_new, wavenumbers_new)`

| Method | Description | Parameters |
|--------|-------------|------------|
| `snv` | Standard Normal Variate — row-wise normalize (mean=0, std=1) | — |
| `msc` | Multiplicative Scatter Correction — correct to mean spectrum | — |
| `deriv1` | Savitzky-Golay 1st derivative | `window` (default 15), `polyorder` (default 2) |
| `deriv2` | Savitzky-Golay 2nd derivative | `window` (default 15), `polyorder` (default 2) |
| `baseline` | Detrend — subtract fitted straight line per spectrum | — |
| `range_cut` | Restrict to wavenumber range | `min_wn`, `max_wn` |
| `mean_center` | Subtract column mean (standard before PCA/PLS) | — |

Pipeline = ordered list of steps: `[{"method": "snv"}, {"method": "deriv1", "params": {"window": 15}}]`

Applied sequentially. Frontend shows preview: raw vs preprocessed overlay.

## Models (`models.py`)

### PCA

- `sklearn.decomposition.PCA`
- Input: preprocessed X
- User selects max components (default: min(n_samples, 10))
- Returns: scores (T), loadings (P), explained_variance_ratio, T² (Hotelling), Q (residuals)
- **Charts:**
  - Scores plot (PCx vs PCy) — color by target value or sample name
  - Loadings plot — wavenumber axis, shows influential regions
  - Scree plot — explained variance per component (bar + cumulative line)
  - T² vs Q — outlier detection (Hotelling T² and Q residuals with 95% confidence limits)

### PLS

- `sklearn.cross_decomposition.PLSRegression`
- Input: preprocessed X, target y, n_lv
- CV strategy: LOO if n_samples ≤ 50, else 10-fold
- Returns: predictions (cal + cv), metrics (RMSEC, RMSECV, R², R²cv, bias), regression_coefficients
- **Charts:**
  - Predicted vs Measured (calibration points + CV points, identity line)
  - RMSECV vs n_LV (sweep 1..max_lv, helps select optimal)
  - Regression coefficients (wavenumber axis — which bands drive prediction)
  - Residuals plot (predicted vs residual)

## API Endpoints (`app.py`)

```
GET  /api/projects                          → list project directories
POST /api/projects/{name}/create            → create new project (empty dirs + config)
GET  /api/projects/{name}/data              → raw spectra matrix, references, wavenumbers, sample_names
GET  /api/projects/{name}/spectra           → raw spectra for overlay plot
POST /api/projects/{name}/preprocess        → body: {pipeline} → preprocessed X
POST /api/projects/{name}/pca               → body: {n_components, pipeline} → scores, loadings, variance, t2, q
POST /api/projects/{name}/pls               → body: {target, n_lv, pipeline, cv_method} → metrics, predicted, coefficients
```

Response format:
- Matrices as lists of lists (JSON) — Plotly.js consumes directly
- Wavenumbers as flat array
- Metrics as flat object: `{rmsec, rmsecv, r2, r2cv, bias}`
- All computation server-side, frontend only renders

## Frontend (`static/index.html`)

### Layout

```
┌──────────────────────────────────────────────────┐
│  Toolbar: [Project ▾] [Preprocessing ▾] [Refresh]│
├──────────┬───────────────────────────────────────┤
│          │                                       │
│  Sidebar │         Main Chart Area               │
│          │         (Plotly.js)                    │
│  Tabs:   │                                       │
│  - Widma │                                       │
│  - PCA   │                                       │
│  - PLS   │                                       │
│          │                                       │
├──────────┴───────────────────────────────────────┤
│  Status: "45 spectra, 3 targets, pipeline:       │
│  SNV → Deriv1 → Mean center"                     │
└──────────────────────────────────────────────────┘
```

### Sidebar Tabs

1. **Widma** — raw/preprocessed spectra overlay, toggle individual spectra
2. **PCA** — component selector (PC x/y dropdowns), scores/loadings/scree toggle, color-by dropdown (target or sample)
3. **PLS** — target dropdown, LV count slider, metrics display (RMSEC, RMSECV, R², R²cv), chart selector (pred vs meas, RMSECV vs LV, coefficients, residuals)

### Preprocessing Dialog

- Modal with ordered list of pipeline steps
- Add step from dropdown, configure parameters
- Drag & drop to reorder
- "Apply" → recompute, refresh all views

### Interactions

- Plotly hover: sample name + values
- Scores plot point selection → highlights corresponding spectra
- LV slider change → live RMSECV update

Single HTML file, inline JS, no framework, no build step.
