# NIR Calibration Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a web-based NIR spectroscopy calibration tool with import, preprocessing, PCA exploration, and PLS model building.

**Architecture:** FastAPI backend serves API endpoints for data loading, preprocessing, PCA, and PLS. Single-file HTML frontend with Plotly.js for interactive charts. Projects stored as directories with CSV spectra + references.

**Tech Stack:** Python 3, FastAPI, uvicorn, scikit-learn, numpy, scipy, Plotly.js

---

## File Structure

```
~/Desktop/nir-calibration/
├── app.py              # FastAPI backend + all API routes
├── data_loader.py      # CSV spectra import + referencje.csv parsing
├── preprocess.py       # 7 preprocessing functions + pipeline runner
├── models.py           # PCA + PLS wrappers with metrics
├── static/
│   └── index.html      # SPA frontend (Plotly.js, no build)
├── tests/
│   ├── __init__.py
│   ├── test_data_loader.py
│   ├── test_preprocess.py
│   └── test_models.py
├── projects/
│   └── example/
│       ├── widma/
│       │   ├── probka_001.csv
│       │   ├── probka_002.csv
│       │   └── probka_003.csv
│       └── referencje.csv
└── requirements.txt
```

---

### Task 1: Project scaffold + example data

**Files:**
- Create: `~/Desktop/nir-calibration/requirements.txt`
- Create: `~/Desktop/nir-calibration/tests/__init__.py`
- Create: `~/Desktop/nir-calibration/projects/example/widma/probka_001.csv`
- Create: `~/Desktop/nir-calibration/projects/example/widma/probka_002.csv`
- Create: `~/Desktop/nir-calibration/projects/example/widma/probka_003.csv`
- Create: `~/Desktop/nir-calibration/projects/example/referencje.csv`

- [ ] **Step 1: Create project directory and requirements.txt**

```
~/Desktop/nir-calibration/requirements.txt:

fastapi>=0.110
uvicorn>=0.29
scikit-learn>=1.4
numpy>=1.26
scipy>=1.12
pytest>=8.0
```

- [ ] **Step 2: Create example spectra (synthetic, 3 samples, 50 wavenumber points)**

`projects/example/widma/probka_001.csv`:
```csv
4000,0.452
3960,0.448
3920,0.455
3880,0.461
3840,0.470
3800,0.482
3760,0.491
3720,0.505
3680,0.518
3640,0.530
3600,0.545
3560,0.558
3520,0.570
3480,0.581
3440,0.590
3400,0.598
3360,0.605
3320,0.610
3280,0.614
3240,0.617
3200,0.619
3160,0.620
3120,0.618
3080,0.615
3040,0.611
3000,0.605
2960,0.598
2920,0.590
2880,0.581
2840,0.570
2800,0.558
2760,0.545
2720,0.530
2680,0.515
2640,0.498
2600,0.480
2560,0.462
2520,0.443
2480,0.425
2440,0.408
2400,0.392
2360,0.378
2320,0.366
2280,0.357
2240,0.350
2200,0.345
2160,0.342
2120,0.340
2080,0.339
2040,0.338
```

`projects/example/widma/probka_002.csv`:
```csv
4000,0.510
3960,0.505
3920,0.512
3880,0.520
3840,0.531
3800,0.545
3760,0.556
3720,0.572
3680,0.588
3640,0.602
3600,0.620
3560,0.635
3520,0.650
3480,0.663
3440,0.674
3400,0.683
3360,0.691
3320,0.697
3280,0.701
3240,0.704
3200,0.706
3160,0.707
3120,0.705
3080,0.702
3040,0.697
3000,0.690
2960,0.682
2920,0.672
2880,0.661
2840,0.648
2800,0.634
2760,0.618
2720,0.601
2680,0.583
2640,0.564
2600,0.543
2560,0.522
2520,0.501
2480,0.480
2440,0.460
2400,0.441
2360,0.424
2320,0.410
2280,0.398
2240,0.389
2200,0.383
2160,0.378
2120,0.375
2080,0.373
2040,0.372
```

`projects/example/widma/probka_003.csv`:
```csv
4000,0.380
3960,0.377
3920,0.383
3880,0.390
3840,0.398
3800,0.408
3760,0.416
3720,0.428
3680,0.440
3640,0.450
3600,0.462
3560,0.473
3520,0.483
3480,0.492
3440,0.499
3400,0.505
3360,0.510
3320,0.514
3280,0.517
3240,0.519
3200,0.520
3160,0.520
3120,0.519
3080,0.516
3040,0.512
3000,0.507
2960,0.501
2920,0.493
2880,0.484
2840,0.474
2800,0.463
2760,0.451
2720,0.438
2680,0.424
2640,0.409
2600,0.393
2560,0.377
2520,0.362
2480,0.347
2440,0.333
2400,0.321
2360,0.310
2320,0.301
2280,0.294
2240,0.289
2200,0.285
2160,0.282
2120,0.280
2080,0.279
2040,0.278
```

`projects/example/referencje.csv`:
```csv
plik,procent_sa,nd20
probka_001.csv,38.3,1.407
probka_002.csv,42.1,1.412
probka_003.csv,35.0,1.401
```

- [ ] **Step 3: Create tests/__init__.py (empty)**

- [ ] **Step 4: Init git repo + commit**

```bash
cd ~/Desktop/nir-calibration
git init
git add requirements.txt tests/__init__.py projects/
git commit -m "init: project scaffold with example NIR data"
```

- [ ] **Step 5: Install dependencies**

```bash
cd ~/Desktop/nir-calibration
pip install -r requirements.txt
```

---

### Task 2: Data loader

**Files:**
- Create: `~/Desktop/nir-calibration/data_loader.py`
- Create: `~/Desktop/nir-calibration/tests/test_data_loader.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_data_loader.py
import numpy as np
import pytest
from pathlib import Path

EXAMPLE_DIR = Path(__file__).parent.parent / "projects" / "example"


def test_load_single_spectrum():
    from data_loader import load_spectrum
    wn, ab = load_spectrum(EXAMPLE_DIR / "widma" / "probka_001.csv")
    assert isinstance(wn, np.ndarray)
    assert isinstance(ab, np.ndarray)
    assert len(wn) == 50
    assert len(ab) == 50
    assert wn[0] == 4000
    assert wn[-1] == 2040
    assert abs(ab[0] - 0.452) < 1e-6


def test_load_project():
    from data_loader import load_project
    data = load_project(EXAMPLE_DIR)
    assert data["X"].shape == (3, 50)
    assert len(data["wavenumbers"]) == 50
    assert len(data["sample_names"]) == 3
    assert "probka_001.csv" in data["sample_names"]
    assert "procent_sa" in data["targets"]
    assert "nd20" in data["targets"]
    assert len(data["targets"]["procent_sa"]) == 3
    assert abs(data["targets"]["procent_sa"][0] - 38.3) < 1e-6


def test_load_project_missing_reference():
    """Samples without references should still load (targets = NaN)."""
    from data_loader import load_project
    import tempfile, shutil
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        widma = tmp / "widma"
        widma.mkdir()
        # Copy one spectrum
        shutil.copy(EXAMPLE_DIR / "widma" / "probka_001.csv", widma / "probka_001.csv")
        # No referencje.csv
        data = load_project(tmp)
        assert data["X"].shape == (1, 50)
        assert data["targets"] == {}


def test_separator_autodetect(tmp_path):
    from data_loader import load_spectrum
    # Semicolon separated
    csv_path = tmp_path / "test.csv"
    csv_path.write_text("4000;0.5\n3960;0.6\n")
    wn, ab = load_spectrum(csv_path)
    assert len(wn) == 2
    assert wn[0] == 4000
    assert abs(ab[0] - 0.5) < 1e-6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Desktop/nir-calibration && python -m pytest tests/test_data_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'data_loader'`

- [ ] **Step 3: Implement data_loader.py**

```python
"""data_loader.py — Load NIR spectra from CSV files + reference values."""

import csv
import numpy as np
from pathlib import Path


def _detect_separator(line: str) -> str:
    """Detect CSV separator from first data line."""
    for sep in ["\t", ";", ","]:
        if sep in line:
            return sep
    return ","


def load_spectrum(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load a single spectrum CSV (wavenumber, absorbance). Returns (wn, ab) arrays."""
    text = path.read_text().strip()
    lines = text.splitlines()

    # Skip header if first line contains non-numeric characters
    start = 0
    try:
        float(lines[0].replace(",", ".").split()[0].split(";")[0].split("\t")[0])
    except ValueError:
        start = 1

    sep = _detect_separator(lines[start])
    wavenumbers = []
    absorbances = []
    for line in lines[start:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(sep)
        wavenumbers.append(float(parts[0]))
        absorbances.append(float(parts[1]))

    return np.array(wavenumbers), np.array(absorbances)


def _load_references(path: Path) -> dict:
    """Load referencje.csv → {filename: {target: value}}."""
    if not path.exists():
        return {}
    text = path.read_text().strip()
    lines = text.splitlines()
    sep = _detect_separator(lines[0])
    reader = csv.DictReader(lines, delimiter=sep)
    refs = {}
    for row in reader:
        fname = row.get("plik", "").strip()
        if not fname:
            continue
        values = {}
        for k, v in row.items():
            if k == "plik":
                continue
            try:
                values[k] = float(v)
            except (ValueError, TypeError):
                pass
        refs[fname] = values
    return refs


def load_project(project_dir: Path) -> dict:
    """Load all spectra + references from a project directory.

    Returns:
        {
            "X": np.ndarray (n_samples, n_wavenumbers),
            "wavenumbers": np.ndarray (n_wavenumbers,),
            "sample_names": list[str],
            "targets": {target_name: np.ndarray (n_samples,)},
        }
    """
    widma_dir = project_dir / "widma"
    if not widma_dir.exists():
        raise FileNotFoundError(f"No widma/ directory in {project_dir}")

    csv_files = sorted(widma_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files in {widma_dir}")

    # Load all spectra
    spectra = []
    sample_names = []
    for f in csv_files:
        wn, ab = load_spectrum(f)
        spectra.append((wn, ab, f.name))
        sample_names.append(f.name)

    # Use first spectrum's wavenumbers as reference grid
    ref_wn = spectra[0][0]

    # Build X matrix — interpolate if needed
    rows = []
    for wn, ab, name in spectra:
        if np.array_equal(wn, ref_wn):
            rows.append(ab)
        else:
            interpolated = np.interp(ref_wn, wn[::-1], ab[::-1])
            rows.append(interpolated if ref_wn[0] > ref_wn[-1] else np.interp(ref_wn, wn, ab))
    X = np.array(rows)

    # Load references
    refs = _load_references(project_dir / "referencje.csv")

    # Build targets dict
    targets = {}
    if refs:
        target_names = set()
        for v in refs.values():
            target_names.update(v.keys())
        for tname in sorted(target_names):
            values = []
            for sname in sample_names:
                ref = refs.get(sname, {})
                values.append(ref.get(tname, float("nan")))
            targets[tname] = np.array(values)

    return {
        "X": X,
        "wavenumbers": ref_wn,
        "sample_names": sample_names,
        "targets": targets,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/Desktop/nir-calibration && python -m pytest tests/test_data_loader.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add data_loader.py tests/test_data_loader.py
git commit -m "feat: data loader — CSV spectra + references import"
```

---

### Task 3: Preprocessing

**Files:**
- Create: `~/Desktop/nir-calibration/preprocess.py`
- Create: `~/Desktop/nir-calibration/tests/test_preprocess.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_preprocess.py
import numpy as np
import pytest


def _make_X():
    """3 spectra, 10 wavenumber points."""
    np.random.seed(42)
    wn = np.linspace(4000, 2000, 10)
    X = np.random.rand(3, 10) + np.array([[0.5], [1.0], [0.2]])  # offset per sample
    return X, wn


def test_snv():
    from preprocess import snv
    X, wn = _make_X()
    X_new, wn_new = snv(X, wn)
    assert X_new.shape == X.shape
    np.testing.assert_array_equal(wn_new, wn)
    # Each row should have mean≈0, std≈1
    for i in range(X_new.shape[0]):
        assert abs(np.mean(X_new[i])) < 1e-10
        assert abs(np.std(X_new[i], ddof=0) - 1.0) < 1e-10


def test_msc():
    from preprocess import msc
    X, wn = _make_X()
    X_new, wn_new = msc(X, wn)
    assert X_new.shape == X.shape


def test_deriv1():
    from preprocess import deriv1
    X, wn = _make_X()
    X_new, wn_new = deriv1(X, wn, window=5, polyorder=2)
    assert X_new.shape == X.shape


def test_deriv2():
    from preprocess import deriv2
    X, wn = _make_X()
    X_new, wn_new = deriv2(X, wn, window=5, polyorder=3)
    assert X_new.shape == X.shape


def test_baseline():
    from preprocess import baseline
    X, wn = _make_X()
    # Add linear trend
    trend = np.linspace(0, 1, 10)
    X_trended = X + trend[np.newaxis, :]
    X_new, wn_new = baseline(X_trended, wn)
    assert X_new.shape == X.shape


def test_range_cut():
    from preprocess import range_cut
    X, wn = _make_X()
    X_new, wn_new = range_cut(X, wn, min_wn=2500, max_wn=3500)
    assert X_new.shape[0] == 3
    assert X_new.shape[1] < 10
    assert wn_new.min() >= 2500
    assert wn_new.max() <= 3500


def test_mean_center():
    from preprocess import mean_center
    X, wn = _make_X()
    X_new, wn_new = mean_center(X, wn)
    col_means = np.mean(X_new, axis=0)
    np.testing.assert_allclose(col_means, 0, atol=1e-10)


def test_apply_pipeline():
    from preprocess import apply_pipeline
    X, wn = _make_X()
    pipeline = [
        {"method": "snv"},
        {"method": "mean_center"},
    ]
    X_new, wn_new = apply_pipeline(X, wn, pipeline)
    assert X_new.shape == X.shape
    col_means = np.mean(X_new, axis=0)
    np.testing.assert_allclose(col_means, 0, atol=1e-10)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Desktop/nir-calibration && python -m pytest tests/test_preprocess.py -v`
Expected: FAIL

- [ ] **Step 3: Implement preprocess.py**

```python
"""preprocess.py — NIR spectra preprocessing functions."""

import numpy as np
from scipy.signal import savgol_filter


def snv(X: np.ndarray, wn: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Standard Normal Variate — row-wise normalize (mean=0, std=1)."""
    means = X.mean(axis=1, keepdims=True)
    stds = X.std(axis=1, keepdims=True, ddof=0)
    stds[stds == 0] = 1.0
    return (X - means) / stds, wn


def msc(X: np.ndarray, wn: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Multiplicative Scatter Correction — correct to mean spectrum."""
    mean_spectrum = X.mean(axis=0)
    X_new = np.zeros_like(X)
    for i in range(X.shape[0]):
        coef = np.polyfit(mean_spectrum, X[i], 1)
        X_new[i] = (X[i] - coef[1]) / coef[0]
    return X_new, wn


def deriv1(X: np.ndarray, wn: np.ndarray, window: int = 15,
           polyorder: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """Savitzky-Golay 1st derivative."""
    w = min(window, X.shape[1])
    if w % 2 == 0:
        w -= 1
    return savgol_filter(X, window_length=w, polyorder=polyorder, deriv=1, axis=1), wn


def deriv2(X: np.ndarray, wn: np.ndarray, window: int = 15,
           polyorder: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """Savitzky-Golay 2nd derivative."""
    w = min(window, X.shape[1])
    if w % 2 == 0:
        w -= 1
    po = min(polyorder, w - 1)
    if po < 2:
        po = 2
        w = max(w, po + 1)
        if w % 2 == 0:
            w += 1
    return savgol_filter(X, window_length=w, polyorder=po, deriv=2, axis=1), wn


def baseline(X: np.ndarray, wn: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Detrend — subtract fitted straight line per spectrum."""
    n_cols = X.shape[1]
    x = np.arange(n_cols)
    X_new = np.zeros_like(X)
    for i in range(X.shape[0]):
        coef = np.polyfit(x, X[i], 1)
        trend = np.polyval(coef, x)
        X_new[i] = X[i] - trend
    return X_new, wn


def range_cut(X: np.ndarray, wn: np.ndarray, min_wn: float = None,
              max_wn: float = None) -> tuple[np.ndarray, np.ndarray]:
    """Restrict to wavenumber range [min_wn, max_wn]."""
    mask = np.ones(len(wn), dtype=bool)
    if min_wn is not None:
        mask &= wn >= min_wn
    if max_wn is not None:
        mask &= wn <= max_wn
    return X[:, mask], wn[mask]


def mean_center(X: np.ndarray, wn: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Subtract column mean."""
    return X - X.mean(axis=0, keepdims=True), wn


METHODS = {
    "snv": snv,
    "msc": msc,
    "deriv1": deriv1,
    "deriv2": deriv2,
    "baseline": baseline,
    "range_cut": range_cut,
    "mean_center": mean_center,
}


def apply_pipeline(X: np.ndarray, wn: np.ndarray,
                   pipeline: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Apply a sequence of preprocessing steps."""
    for step in pipeline:
        method = step["method"]
        params = step.get("params", {})
        func = METHODS[method]
        X, wn = func(X, wn, **params)
    return X, wn
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/Desktop/nir-calibration && python -m pytest tests/test_preprocess.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add preprocess.py tests/test_preprocess.py
git commit -m "feat: preprocessing — SNV, MSC, derivatives, baseline, range cut, mean center"
```

---

### Task 4: PCA model

**Files:**
- Create: `~/Desktop/nir-calibration/models.py`
- Create: `~/Desktop/nir-calibration/tests/test_models.py`

- [ ] **Step 1: Write PCA tests**

```python
# tests/test_models.py
import numpy as np
import pytest


def _make_data():
    np.random.seed(42)
    X = np.random.rand(10, 50)
    return X


def test_run_pca():
    from models import run_pca
    X = _make_data()
    result = run_pca(X, n_components=3)
    assert result["scores"].shape == (10, 3)
    assert result["loadings"].shape == (3, 50)
    assert len(result["explained_variance"]) == 3
    assert all(0 <= v <= 1 for v in result["explained_variance"])
    assert len(result["t2"]) == 10
    assert len(result["q"]) == 10


def test_pca_t2_limit():
    from models import run_pca
    X = _make_data()
    result = run_pca(X, n_components=2)
    assert "t2_limit" in result
    assert result["t2_limit"] > 0


def test_pca_q_limit():
    from models import run_pca
    X = _make_data()
    result = run_pca(X, n_components=2)
    assert "q_limit" in result
    assert result["q_limit"] > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Desktop/nir-calibration && python -m pytest tests/test_models.py::test_run_pca -v`
Expected: FAIL

- [ ] **Step 3: Implement PCA in models.py**

```python
"""models.py — PCA and PLS model wrappers."""

import numpy as np
from sklearn.decomposition import PCA
from sklearn.cross_decomposition import PLSRegression
from sklearn.model_selection import cross_val_predict, LeaveOneOut, KFold
from scipy import stats


def run_pca(X: np.ndarray, n_components: int = None) -> dict:
    """Run PCA on preprocessed matrix X.

    Returns dict with: scores, loadings, explained_variance, t2, q, t2_limit, q_limit.
    """
    if n_components is None:
        n_components = min(X.shape[0], X.shape[1], 10)

    pca = PCA(n_components=n_components)
    scores = pca.fit_transform(X)
    loadings = pca.components_

    # Hotelling T²
    score_vars = np.var(scores, axis=0, ddof=1)
    score_vars[score_vars == 0] = 1.0
    t2 = np.sum((scores ** 2) / score_vars, axis=1)

    # T² limit (F-distribution, 95%)
    n = X.shape[0]
    p = n_components
    if n > p:
        t2_limit = (p * (n - 1) * (n + 1)) / (n * (n - p)) * stats.f.ppf(0.95, p, n - p)
    else:
        t2_limit = float(np.max(t2) * 1.5)

    # Q residuals (squared prediction error)
    X_reconstructed = scores @ loadings + pca.mean_
    q = np.sum((X - X_reconstructed) ** 2, axis=1)

    # Q limit (approximate, based on chi² of residual eigenvalues)
    residual_var = np.var(X - X_reconstructed, axis=0)
    theta1 = np.sum(residual_var)
    theta2 = np.sum(residual_var ** 2)
    if theta2 > 0 and theta1 > 0:
        h0 = 1 - (2 * theta1 * theta2) / (3 * theta1 ** 2)
        if abs(h0) > 1e-10:
            ca = stats.norm.ppf(0.95)
            q_limit = theta1 * (1 + ca * np.sqrt(2 * theta2) / theta1) ** (1 / h0)
        else:
            q_limit = float(np.percentile(q, 95))
    else:
        q_limit = float(np.percentile(q, 95)) if len(q) > 0 else 0.0

    return {
        "scores": scores,
        "loadings": loadings,
        "explained_variance": pca.explained_variance_ratio_.tolist(),
        "t2": t2.tolist(),
        "q": q.tolist(),
        "t2_limit": float(t2_limit),
        "q_limit": float(q_limit),
    }
```

- [ ] **Step 4: Run tests**

Run: `cd ~/Desktop/nir-calibration && python -m pytest tests/test_models.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add models.py tests/test_models.py
git commit -m "feat: PCA model with T² + Q residuals and confidence limits"
```

---

### Task 5: PLS model

**Files:**
- Modify: `~/Desktop/nir-calibration/models.py`
- Modify: `~/Desktop/nir-calibration/tests/test_models.py`

- [ ] **Step 1: Write PLS tests**

Add to `tests/test_models.py`:

```python
def test_run_pls():
    from models import run_pls
    np.random.seed(42)
    X = np.random.rand(20, 50)
    y = X[:, 10] * 5 + X[:, 20] * 3 + np.random.rand(20) * 0.1
    result = run_pls(X, y, n_lv=3)
    assert "rmsec" in result
    assert "rmsecv" in result
    assert "r2" in result
    assert "r2cv" in result
    assert "bias" in result
    assert len(result["y_cal"]) == 20
    assert len(result["y_cv"]) == 20
    assert len(result["coefficients"]) == 50
    assert result["rmsec"] < result["rmsecv"]  # cal error < cv error
    assert result["r2"] > 0.5  # should fit reasonably


def test_pls_lv_sweep():
    from models import pls_lv_sweep
    np.random.seed(42)
    X = np.random.rand(20, 50)
    y = X[:, 10] * 5 + X[:, 20] * 3 + np.random.rand(20) * 0.1
    result = pls_lv_sweep(X, y, max_lv=5)
    assert len(result["rmsecv_values"]) == 5
    assert len(result["rmsec_values"]) == 5
    assert result["rmsecv_values"][0] > 0


def test_pls_loo_small():
    """Small dataset should use LOO."""
    from models import run_pls
    np.random.seed(42)
    X = np.random.rand(10, 50)
    y = np.random.rand(10)
    result = run_pls(X, y, n_lv=2)
    assert "rmsecv" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Desktop/nir-calibration && python -m pytest tests/test_models.py::test_run_pls -v`
Expected: FAIL — `ImportError: cannot import name 'run_pls'`

- [ ] **Step 3: Add PLS functions to models.py**

Add after `run_pca`:

```python
def run_pls(X: np.ndarray, y: np.ndarray, n_lv: int = 3,
            cv_method: str = "auto") -> dict:
    """Run PLS regression with cross-validation.

    Returns dict with: rmsec, rmsecv, r2, r2cv, bias, y_cal, y_cv, coefficients.
    """
    n_samples = X.shape[0]
    n_lv = min(n_lv, min(X.shape[0] - 1, X.shape[1]))

    # Fit calibration model
    pls = PLSRegression(n_components=n_lv)
    pls.fit(X, y)
    y_cal = pls.predict(X).ravel()

    # Cross-validation
    if cv_method == "auto":
        cv = LeaveOneOut() if n_samples <= 50 else KFold(n_splits=10, shuffle=True, random_state=42)
    elif cv_method == "loo":
        cv = LeaveOneOut()
    else:
        cv = KFold(n_splits=10, shuffle=True, random_state=42)

    y_cv = cross_val_predict(PLSRegression(n_components=n_lv), X, y, cv=cv).ravel()

    # Metrics
    rmsec = float(np.sqrt(np.mean((y - y_cal) ** 2)))
    rmsecv = float(np.sqrt(np.mean((y - y_cv) ** 2)))
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = float(1 - np.sum((y - y_cal) ** 2) / ss_tot) if ss_tot > 0 else 0.0
    r2cv = float(1 - np.sum((y - y_cv) ** 2) / ss_tot) if ss_tot > 0 else 0.0
    bias = float(np.mean(y_cv - y))

    # Regression coefficients
    coefficients = pls.coef_.ravel()

    return {
        "rmsec": rmsec,
        "rmsecv": rmsecv,
        "r2": r2,
        "r2cv": r2cv,
        "bias": bias,
        "y_cal": y_cal.tolist(),
        "y_cv": y_cv.tolist(),
        "coefficients": coefficients.tolist(),
    }


def pls_lv_sweep(X: np.ndarray, y: np.ndarray, max_lv: int = 10,
                 cv_method: str = "auto") -> dict:
    """Sweep PLS models from 1..max_lv, return RMSEC + RMSECV per LV count."""
    max_lv = min(max_lv, min(X.shape[0] - 2, X.shape[1]))
    rmsec_values = []
    rmsecv_values = []
    for n in range(1, max_lv + 1):
        result = run_pls(X, y, n_lv=n, cv_method=cv_method)
        rmsec_values.append(result["rmsec"])
        rmsecv_values.append(result["rmsecv"])
    return {
        "lv_range": list(range(1, max_lv + 1)),
        "rmsec_values": rmsec_values,
        "rmsecv_values": rmsecv_values,
    }
```

- [ ] **Step 4: Run tests**

Run: `cd ~/Desktop/nir-calibration && python -m pytest tests/test_models.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add models.py tests/test_models.py
git commit -m "feat: PLS model with cross-validation + LV sweep"
```

---

### Task 6: FastAPI backend

**Files:**
- Create: `~/Desktop/nir-calibration/app.py`

- [ ] **Step 1: Write app.py**

```python
"""app.py — FastAPI backend for NIR calibration tool."""

from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from data_loader import load_project
from preprocess import apply_pipeline
from models import run_pca, run_pls, pls_lv_sweep

app = FastAPI(title="NIR Calibration Tool")

PROJECTS_DIR = Path(__file__).parent / "projects"


# --- Pydantic models ---

class PipelineStep(BaseModel):
    method: str
    params: dict = {}

class PreprocessRequest(BaseModel):
    pipeline: list[PipelineStep] = []

class PCARequest(BaseModel):
    n_components: int = 5
    pipeline: list[PipelineStep] = []

class PLSRequest(BaseModel):
    target: str
    n_lv: int = 3
    pipeline: list[PipelineStep] = []
    cv_method: str = "auto"
    max_lv: int | None = None  # if set, do LV sweep instead


# --- Helpers ---

def _load(name: str) -> dict:
    project_dir = PROJECTS_DIR / name
    if not project_dir.exists():
        raise HTTPException(404, f"Project '{name}' not found")
    return load_project(project_dir)


def _preprocess(data: dict, pipeline: list[PipelineStep]) -> tuple[np.ndarray, np.ndarray]:
    X = data["X"].copy()
    wn = data["wavenumbers"].copy()
    if pipeline:
        steps = [{"method": s.method, "params": s.params} for s in pipeline]
        X, wn = apply_pipeline(X, wn, steps)
    return X, wn


# --- Routes ---

@app.get("/api/projects")
def list_projects():
    dirs = [d.name for d in sorted(PROJECTS_DIR.iterdir()) if d.is_dir()]
    return {"projects": dirs}


@app.get("/api/projects/{name}/data")
def get_data(name: str):
    data = _load(name)
    return {
        "X": data["X"].tolist(),
        "wavenumbers": data["wavenumbers"].tolist(),
        "sample_names": data["sample_names"],
        "targets": {k: v.tolist() for k, v in data["targets"].items()},
    }


@app.get("/api/projects/{name}/spectra")
def get_spectra(name: str):
    data = _load(name)
    return {
        "wavenumbers": data["wavenumbers"].tolist(),
        "spectra": data["X"].tolist(),
        "sample_names": data["sample_names"],
    }


@app.post("/api/projects/{name}/preprocess")
def preprocess(name: str, req: PreprocessRequest):
    data = _load(name)
    X, wn = _preprocess(data, req.pipeline)
    return {
        "X": X.tolist(),
        "wavenumbers": wn.tolist(),
        "sample_names": data["sample_names"],
    }


@app.post("/api/projects/{name}/pca")
def pca(name: str, req: PCARequest):
    data = _load(name)
    X, wn = _preprocess(data, req.pipeline)
    result = run_pca(X, n_components=req.n_components)
    result["wavenumbers"] = wn.tolist()
    result["sample_names"] = data["sample_names"]
    # Convert numpy arrays to lists for JSON
    result["scores"] = result["scores"].tolist()
    result["loadings"] = result["loadings"].tolist()
    return result


@app.post("/api/projects/{name}/pls")
def pls(name: str, req: PLSRequest):
    data = _load(name)
    X, wn = _preprocess(data, req.pipeline)

    target_name = req.target
    if target_name not in data["targets"]:
        raise HTTPException(400, f"Unknown target: {target_name}. Available: {list(data['targets'].keys())}")

    y = data["targets"][target_name]
    # Filter out NaN references
    mask = ~np.isnan(y)
    X_filtered = X[mask]
    y_filtered = y[mask]

    if len(y_filtered) < 3:
        raise HTTPException(400, f"Need at least 3 samples with reference values for '{target_name}'")

    if req.max_lv is not None:
        sweep = pls_lv_sweep(X_filtered, y_filtered, max_lv=req.max_lv, cv_method=req.cv_method)
        return {**sweep, "sample_names": [s for s, m in zip(data["sample_names"], mask) if m]}

    result = run_pls(X_filtered, y_filtered, n_lv=req.n_lv, cv_method=req.cv_method)
    result["wavenumbers"] = wn.tolist()
    result["sample_names"] = [s for s, m in zip(data["sample_names"], mask) if m]
    result["y_ref"] = y_filtered.tolist()
    return result


# --- Static files + SPA ---

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
```

- [ ] **Step 2: Smoke test**

Run: `cd ~/Desktop/nir-calibration && python -c "from app import app; print('import OK')"`
Expected: `import OK`

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: FastAPI backend with all API endpoints"
```

---

### Task 7: Frontend — HTML shell + spectra view

**Files:**
- Create: `~/Desktop/nir-calibration/static/index.html`

- [ ] **Step 1: Create index.html with layout + spectra tab**

```html
<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<title>NIR Calibration Tool</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #1a1a2e; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }

/* Toolbar */
.toolbar { display: flex; align-items: center; gap: 12px; padding: 8px 16px; background: #16213e; border-bottom: 1px solid #333; }
.toolbar select, .toolbar button { padding: 6px 12px; border-radius: 4px; border: 1px solid #444; background: #1a1a2e; color: #e0e0e0; font-size: 13px; cursor: pointer; }
.toolbar button:hover { background: #0f3460; }
.toolbar .title { font-weight: 600; font-size: 15px; color: #64ffda; }

/* Main area */
.main { display: flex; flex: 1; overflow: hidden; }

/* Sidebar */
.sidebar { width: 220px; background: #16213e; border-right: 1px solid #333; display: flex; flex-direction: column; }
.sidebar .tabs { display: flex; border-bottom: 1px solid #333; }
.sidebar .tabs button { flex: 1; padding: 10px 4px; background: none; border: none; color: #999; cursor: pointer; font-size: 12px; font-weight: 600; text-transform: uppercase; }
.sidebar .tabs button.active { color: #64ffda; border-bottom: 2px solid #64ffda; }
.sidebar .panel { padding: 12px; flex: 1; overflow-y: auto; }
.sidebar .panel.hidden { display: none; }

/* Controls */
.control-group { margin-bottom: 12px; }
.control-group label { display: block; font-size: 11px; color: #999; margin-bottom: 4px; text-transform: uppercase; }
.control-group select, .control-group input { width: 100%; padding: 6px 8px; border-radius: 4px; border: 1px solid #444; background: #1a1a2e; color: #e0e0e0; font-size: 13px; }
.control-group input[type=range] { padding: 0; }

/* Metrics */
.metrics { font-size: 12px; }
.metrics .row { display: flex; justify-content: space-between; padding: 3px 0; border-bottom: 1px solid #222; }
.metrics .label { color: #999; }
.metrics .value { color: #64ffda; font-weight: 600; }

/* Chart */
.chart-area { flex: 1; display: flex; align-items: center; justify-content: center; }
#chart { width: 100%; height: 100%; }

/* Status */
.status { padding: 6px 16px; background: #16213e; border-top: 1px solid #333; font-size: 12px; color: #999; }

/* Preprocessing modal */
.modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 100; }
.modal-overlay.show { display: flex; align-items: center; justify-content: center; }
.modal { background: #16213e; border: 1px solid #444; border-radius: 8px; padding: 20px; width: 500px; max-height: 80vh; overflow-y: auto; }
.modal h3 { margin-bottom: 12px; color: #64ffda; }
.modal .step-row { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; padding: 6px; background: #1a1a2e; border-radius: 4px; }
.modal .step-row select, .modal .step-row input { padding: 4px 8px; border-radius: 4px; border: 1px solid #444; background: #0e1628; color: #e0e0e0; font-size: 12px; }
.modal .step-row .remove-btn { background: #e74c3c; color: white; border: none; border-radius: 4px; padding: 4px 8px; cursor: pointer; font-size: 11px; }
.modal button.primary { background: #0f3460; color: #64ffda; border: 1px solid #64ffda; padding: 8px 16px; border-radius: 4px; cursor: pointer; margin-top: 8px; }
.modal button.secondary { background: none; color: #999; border: 1px solid #444; padding: 8px 16px; border-radius: 4px; cursor: pointer; margin-top: 8px; margin-left: 8px; }
</style>
</head>
<body>

<div class="toolbar">
    <span class="title">NIR Calibration</span>
    <select id="projectSelect"></select>
    <button onclick="openPreprocessing()">Preprocessing</button>
    <button onclick="refresh()">Refresh</button>
</div>

<div class="main">
    <div class="sidebar">
        <div class="tabs">
            <button class="active" onclick="switchTab('widma')">Widma</button>
            <button onclick="switchTab('pca')">PCA</button>
            <button onclick="switchTab('pls')">PLS</button>
        </div>

        <!-- Widma panel -->
        <div class="panel" id="panel-widma">
            <div class="control-group">
                <label>Display</label>
                <select id="spectraMode" onchange="plotSpectra()">
                    <option value="raw">Raw</option>
                    <option value="preprocessed">Preprocessed</option>
                    <option value="both">Both (overlay)</option>
                </select>
            </div>
        </div>

        <!-- PCA panel -->
        <div class="panel hidden" id="panel-pca">
            <div class="control-group">
                <label>Components</label>
                <input type="number" id="pcaComponents" value="5" min="1" max="20" onchange="runPCA()">
            </div>
            <div class="control-group">
                <label>X axis</label>
                <select id="pcaX" onchange="plotPCA()"><option>PC1</option></select>
            </div>
            <div class="control-group">
                <label>Y axis</label>
                <select id="pcaY" onchange="plotPCA()"><option>PC2</option></select>
            </div>
            <div class="control-group">
                <label>Color by</label>
                <select id="pcaColor" onchange="plotPCA()"><option value="">Sample name</option></select>
            </div>
            <div class="control-group">
                <label>Chart</label>
                <select id="pcaChart" onchange="plotPCA()">
                    <option value="scores">Scores</option>
                    <option value="loadings">Loadings</option>
                    <option value="scree">Scree</option>
                    <option value="t2q">T² vs Q</option>
                </select>
            </div>
        </div>

        <!-- PLS panel -->
        <div class="panel hidden" id="panel-pls">
            <div class="control-group">
                <label>Target</label>
                <select id="plsTarget" onchange="runPLS()"></select>
            </div>
            <div class="control-group">
                <label>Latent Variables</label>
                <input type="range" id="plsLV" min="1" max="15" value="3" oninput="document.getElementById('plsLVval').textContent=this.value; runPLS()">
                <span id="plsLVval" style="font-size:13px;color:#64ffda">3</span>
            </div>
            <div class="control-group">
                <label>Chart</label>
                <select id="plsChart" onchange="plotPLS()">
                    <option value="predmeas">Predicted vs Measured</option>
                    <option value="rmsecv_lv">RMSECV vs LV</option>
                    <option value="coefficients">Regression Coefficients</option>
                    <option value="residuals">Residuals</option>
                </select>
            </div>
            <div class="metrics" id="plsMetrics"></div>
        </div>
    </div>

    <div class="chart-area">
        <div id="chart"></div>
    </div>
</div>

<div class="status" id="status">Ready</div>

<!-- Preprocessing Modal -->
<div class="modal-overlay" id="preprocessModal">
    <div class="modal">
        <h3>Preprocessing Pipeline</h3>
        <div id="pipelineSteps"></div>
        <button class="secondary" onclick="addPipelineStep()">+ Add Step</button>
        <div style="margin-top:16px">
            <button class="primary" onclick="applyPreprocessing()">Apply</button>
            <button class="secondary" onclick="closePreprocessing()">Cancel</button>
        </div>
    </div>
</div>

<script>
// ====================== STATE ======================
const state = {
    project: null,
    projects: [],
    data: null,
    preprocessed: null,
    pipeline: [],
    pcaResult: null,
    plsResult: null,
    plsSweep: null,
    currentTab: 'widma'
};

const API = '/api';
const PLOTLY_LAYOUT = {
    paper_bgcolor: '#1a1a2e', plot_bgcolor: '#1a1a2e',
    font: { color: '#e0e0e0', size: 12 },
    xaxis: { gridcolor: '#333', zerolinecolor: '#444' },
    yaxis: { gridcolor: '#333', zerolinecolor: '#444' },
    margin: { l: 60, r: 30, t: 40, b: 50 },
    legend: { bgcolor: 'rgba(0,0,0,0)' }
};

// ====================== INIT ======================
async function init() {
    const res = await fetch(`${API}/projects`);
    const data = await res.json();
    state.projects = data.projects;
    const sel = document.getElementById('projectSelect');
    sel.innerHTML = data.projects.map(p => `<option value="${p}">${p}</option>`).join('');
    if (data.projects.length > 0) {
        state.project = data.projects[0];
        await loadProject();
    }
    sel.onchange = async () => { state.project = sel.value; await loadProject(); };
}

async function loadProject() {
    setStatus('Loading...');
    const res = await fetch(`${API}/projects/${state.project}/data`);
    state.data = await res.json();
    state.preprocessed = null;
    state.pcaResult = null;
    state.plsResult = null;
    state.plsSweep = null;

    // Populate target dropdowns
    const targets = Object.keys(state.data.targets);
    const plsTarget = document.getElementById('plsTarget');
    plsTarget.innerHTML = targets.map(t => `<option value="${t}">${t}</option>`).join('');

    const pcaColor = document.getElementById('pcaColor');
    pcaColor.innerHTML = '<option value="">Sample name</option>' +
        targets.map(t => `<option value="${t}">${t}</option>`).join('');

    setStatus(`${state.data.sample_names.length} spectra, ${targets.length} targets`);
    plotSpectra();
}

async function refresh() { if (state.project) await loadProject(); }

// ====================== TABS ======================
function switchTab(tab) {
    state.currentTab = tab;
    document.querySelectorAll('.sidebar .tabs button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.sidebar .panel').forEach(p => p.classList.add('hidden'));
    document.querySelector(`.tabs button:nth-child(${tab === 'widma' ? 1 : tab === 'pca' ? 2 : 3})`).classList.add('active');
    document.getElementById(`panel-${tab}`).classList.remove('hidden');
    if (tab === 'widma') plotSpectra();
    else if (tab === 'pca') runPCA();
    else if (tab === 'pls') runPLS();
}

// ====================== SPECTRA ======================
async function plotSpectra() {
    if (!state.data) return;
    const mode = document.getElementById('spectraMode').value;
    const wn = state.data.wavenumbers;
    const traces = [];

    if (mode === 'raw' || mode === 'both') {
        state.data.X.forEach((spec, i) => {
            traces.push({ x: wn, y: spec, name: state.data.sample_names[i],
                type: 'scatter', mode: 'lines', opacity: mode === 'both' ? 0.4 : 0.8 });
        });
    }
    if ((mode === 'preprocessed' || mode === 'both') && state.pipeline.length > 0) {
        if (!state.preprocessed) await runPreprocess();
        if (state.preprocessed) {
            const pwn = state.preprocessed.wavenumbers;
            state.preprocessed.X.forEach((spec, i) => {
                traces.push({ x: pwn, y: spec, name: state.data.sample_names[i] + ' (pp)',
                    type: 'scatter', mode: 'lines', line: { dash: mode === 'both' ? 'dot' : 'solid' } });
            });
        }
    }

    Plotly.react('chart', traces, {
        ...PLOTLY_LAYOUT,
        title: 'Spectra',
        xaxis: { ...PLOTLY_LAYOUT.xaxis, title: 'Wavenumber (cm⁻¹)', autorange: 'reversed' },
        yaxis: { ...PLOTLY_LAYOUT.yaxis, title: 'Absorbance' }
    }, { responsive: true });
}

// ====================== PREPROCESSING ======================
async function runPreprocess() {
    if (!state.project || state.pipeline.length === 0) { state.preprocessed = null; return; }
    const res = await fetch(`${API}/projects/${state.project}/preprocess`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pipeline: state.pipeline })
    });
    state.preprocessed = await res.json();
}

function openPreprocessing() {
    document.getElementById('preprocessModal').classList.add('show');
    renderPipelineSteps();
}
function closePreprocessing() {
    document.getElementById('preprocessModal').classList.remove('show');
}
function renderPipelineSteps() {
    const container = document.getElementById('pipelineSteps');
    const methods = ['snv','msc','deriv1','deriv2','baseline','range_cut','mean_center'];
    container.innerHTML = state.pipeline.map((s, i) => {
        let paramsHtml = '';
        if (s.method === 'deriv1' || s.method === 'deriv2') {
            const w = (s.params && s.params.window) || 15;
            const p = (s.params && s.params.polyorder) || 2;
            paramsHtml = `w:<input type="number" value="${w}" min="3" max="51" step="2" style="width:50px"
                onchange="state.pipeline[${i}].params.window=+this.value">
                p:<input type="number" value="${p}" min="1" max="5" style="width:40px"
                onchange="state.pipeline[${i}].params.polyorder=+this.value">`;
        } else if (s.method === 'range_cut') {
            const mn = (s.params && s.params.min_wn) || 2000;
            const mx = (s.params && s.params.max_wn) || 4000;
            paramsHtml = `min:<input type="number" value="${mn}" style="width:60px"
                onchange="state.pipeline[${i}].params.min_wn=+this.value">
                max:<input type="number" value="${mx}" style="width:60px"
                onchange="state.pipeline[${i}].params.max_wn=+this.value">`;
        }
        return `<div class="step-row">
            <select onchange="state.pipeline[${i}].method=this.value;renderPipelineSteps()">
                ${methods.map(m => `<option value="${m}" ${m===s.method?'selected':''}>${m}</option>`).join('')}
            </select>
            ${paramsHtml}
            <button class="remove-btn" onclick="state.pipeline.splice(${i},1);renderPipelineSteps()">X</button>
        </div>`;
    }).join('');
}
function addPipelineStep() {
    state.pipeline.push({ method: 'snv', params: {} });
    renderPipelineSteps();
}
async function applyPreprocessing() {
    closePreprocessing();
    state.preprocessed = null;
    state.pcaResult = null;
    state.plsResult = null;
    state.plsSweep = null;
    await runPreprocess();
    updateStatusPipeline();
    if (state.currentTab === 'widma') plotSpectra();
    else if (state.currentTab === 'pca') runPCA();
    else if (state.currentTab === 'pls') runPLS();
}
function updateStatusPipeline() {
    const pipe = state.pipeline.map(s => s.method).join(' → ');
    const n = state.data ? state.data.sample_names.length : 0;
    const t = state.data ? Object.keys(state.data.targets).length : 0;
    setStatus(`${n} spectra, ${t} targets${pipe ? ', pipeline: ' + pipe : ''}`);
}

// ====================== PCA ======================
async function runPCA() {
    if (!state.data) return;
    const nc = +document.getElementById('pcaComponents').value;
    setStatus('Running PCA...');
    const res = await fetch(`${API}/projects/${state.project}/pca`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ n_components: nc, pipeline: state.pipeline })
    });
    state.pcaResult = await res.json();
    // Populate PC dropdowns
    const options = Array.from({length: nc}, (_, i) => `<option value="${i}">PC${i+1}</option>`);
    document.getElementById('pcaX').innerHTML = options.join('');
    document.getElementById('pcaY').innerHTML = options.join('');
    document.getElementById('pcaY').value = "1";
    updateStatusPipeline();
    plotPCA();
}

function plotPCA() {
    const r = state.pcaResult;
    if (!r) return;
    const chart = document.getElementById('pcaChart').value;

    if (chart === 'scores') {
        const xi = +document.getElementById('pcaX').value;
        const yi = +document.getElementById('pcaY').value;
        const colorBy = document.getElementById('pcaColor').value;
        let marker = { size: 8 };
        if (colorBy && state.data.targets[colorBy]) {
            marker.color = state.data.targets[colorBy];
            marker.colorscale = 'Viridis';
            marker.colorbar = { title: colorBy };
        }
        Plotly.react('chart', [{
            x: r.scores.map(s => s[xi]), y: r.scores.map(s => s[yi]),
            text: r.sample_names, mode: 'markers+text', textposition: 'top center',
            textfont: { size: 9, color: '#999' }, type: 'scatter', marker
        }], {
            ...PLOTLY_LAYOUT,
            title: `Scores: PC${xi+1} vs PC${yi+1}`,
            xaxis: { ...PLOTLY_LAYOUT.xaxis, title: `PC${xi+1} (${(r.explained_variance[xi]*100).toFixed(1)}%)` },
            yaxis: { ...PLOTLY_LAYOUT.yaxis, title: `PC${yi+1} (${(r.explained_variance[yi]*100).toFixed(1)}%)` }
        }, { responsive: true });

    } else if (chart === 'loadings') {
        const xi = +document.getElementById('pcaX').value;
        Plotly.react('chart', [{
            x: r.wavenumbers, y: r.loadings[xi],
            type: 'scatter', mode: 'lines', name: `PC${xi+1} loadings`
        }], {
            ...PLOTLY_LAYOUT, title: `Loadings PC${xi+1}`,
            xaxis: { ...PLOTLY_LAYOUT.xaxis, title: 'Wavenumber (cm⁻¹)', autorange: 'reversed' },
            yaxis: { ...PLOTLY_LAYOUT.yaxis, title: 'Loading' }
        }, { responsive: true });

    } else if (chart === 'scree') {
        const ev = r.explained_variance;
        const cum = ev.reduce((a, v, i) => { a.push((a[i-1]||0)+v); return a; }, []);
        Plotly.react('chart', [
            { x: ev.map((_, i) => i+1), y: ev.map(v => v*100), type: 'bar', name: 'Individual', marker: { color: '#0f3460' } },
            { x: ev.map((_, i) => i+1), y: cum.map(v => v*100), type: 'scatter', mode: 'lines+markers', name: 'Cumulative', line: { color: '#64ffda' } }
        ], {
            ...PLOTLY_LAYOUT, title: 'Scree Plot',
            xaxis: { ...PLOTLY_LAYOUT.xaxis, title: 'Component', dtick: 1 },
            yaxis: { ...PLOTLY_LAYOUT.yaxis, title: 'Explained Variance (%)' }
        }, { responsive: true });

    } else if (chart === 't2q') {
        Plotly.react('chart', [{
            x: r.t2, y: r.q, text: r.sample_names, mode: 'markers+text',
            textposition: 'top center', textfont: { size: 9, color: '#999' },
            type: 'scatter', marker: { size: 8, color: '#64ffda' }
        }, {
            x: [r.t2_limit, r.t2_limit], y: [0, Math.max(...r.q)*1.2],
            mode: 'lines', line: { color: '#e74c3c', dash: 'dash' }, name: 'T² limit', showlegend: true
        }, {
            x: [0, Math.max(...r.t2)*1.2], y: [r.q_limit, r.q_limit],
            mode: 'lines', line: { color: '#f39c12', dash: 'dash' }, name: 'Q limit', showlegend: true
        }], {
            ...PLOTLY_LAYOUT, title: 'Hotelling T² vs Q Residuals',
            xaxis: { ...PLOTLY_LAYOUT.xaxis, title: 'Hotelling T²' },
            yaxis: { ...PLOTLY_LAYOUT.yaxis, title: 'Q Residuals' }
        }, { responsive: true });
    }
}

// ====================== PLS ======================
let plsDebounce = null;
async function runPLS() {
    if (!state.data) return;
    const target = document.getElementById('plsTarget').value;
    if (!target) return;
    clearTimeout(plsDebounce);
    plsDebounce = setTimeout(async () => {
        const nlv = +document.getElementById('plsLV').value;
        setStatus('Running PLS...');

        // Run single model
        const res = await fetch(`${API}/projects/${state.project}/pls`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target, n_lv: nlv, pipeline: state.pipeline })
        });
        state.plsResult = await res.json();

        // Run LV sweep for RMSECV chart
        const sweepRes = await fetch(`${API}/projects/${state.project}/pls`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target, n_lv: nlv, pipeline: state.pipeline, max_lv: 15 })
        });
        state.plsSweep = await sweepRes.json();

        // Update metrics
        const m = state.plsResult;
        document.getElementById('plsMetrics').innerHTML = `
            <div class="row"><span class="label">RMSEC</span><span class="value">${m.rmsec.toFixed(4)}</span></div>
            <div class="row"><span class="label">RMSECV</span><span class="value">${m.rmsecv.toFixed(4)}</span></div>
            <div class="row"><span class="label">R²</span><span class="value">${m.r2.toFixed(4)}</span></div>
            <div class="row"><span class="label">R²cv</span><span class="value">${m.r2cv.toFixed(4)}</span></div>
            <div class="row"><span class="label">Bias</span><span class="value">${m.bias.toFixed(4)}</span></div>
        `;
        updateStatusPipeline();
        plotPLS();
    }, 300);
}

function plotPLS() {
    const r = state.plsResult;
    if (!r) return;
    const chart = document.getElementById('plsChart').value;

    if (chart === 'predmeas') {
        const minv = Math.min(...r.y_ref, ...r.y_cal);
        const maxv = Math.max(...r.y_ref, ...r.y_cal);
        Plotly.react('chart', [
            { x: r.y_ref, y: r.y_cal, text: r.sample_names, mode: 'markers', name: 'Calibration', marker: { size: 8, color: '#0f3460' }, type: 'scatter' },
            { x: r.y_ref, y: r.y_cv, text: r.sample_names, mode: 'markers', name: 'Cross-validation', marker: { size: 8, color: '#64ffda', symbol: 'diamond' }, type: 'scatter' },
            { x: [minv, maxv], y: [minv, maxv], mode: 'lines', line: { color: '#666', dash: 'dash' }, name: '1:1', showlegend: false }
        ], {
            ...PLOTLY_LAYOUT, title: 'Predicted vs Measured',
            xaxis: { ...PLOTLY_LAYOUT.xaxis, title: 'Measured' },
            yaxis: { ...PLOTLY_LAYOUT.yaxis, title: 'Predicted' }
        }, { responsive: true });

    } else if (chart === 'rmsecv_lv') {
        const sw = state.plsSweep;
        if (!sw) return;
        Plotly.react('chart', [
            { x: sw.lv_range, y: sw.rmsec_values, mode: 'lines+markers', name: 'RMSEC', line: { color: '#0f3460' } },
            { x: sw.lv_range, y: sw.rmsecv_values, mode: 'lines+markers', name: 'RMSECV', line: { color: '#64ffda' } }
        ], {
            ...PLOTLY_LAYOUT, title: 'RMSEC/RMSECV vs Latent Variables',
            xaxis: { ...PLOTLY_LAYOUT.xaxis, title: 'Number of LVs', dtick: 1 },
            yaxis: { ...PLOTLY_LAYOUT.yaxis, title: 'RMSE' }
        }, { responsive: true });

    } else if (chart === 'coefficients') {
        Plotly.react('chart', [{
            x: state.pcaResult ? state.pcaResult.wavenumbers : r.wavenumbers,
            y: r.coefficients, type: 'scatter', mode: 'lines', line: { color: '#64ffda' }
        }], {
            ...PLOTLY_LAYOUT, title: 'PLS Regression Coefficients',
            xaxis: { ...PLOTLY_LAYOUT.xaxis, title: 'Wavenumber (cm⁻¹)', autorange: 'reversed' },
            yaxis: { ...PLOTLY_LAYOUT.yaxis, title: 'Coefficient' }
        }, { responsive: true });

    } else if (chart === 'residuals') {
        const resid = r.y_cv.map((yc, i) => yc - r.y_ref[i]);
        Plotly.react('chart', [{
            x: r.y_cv, y: resid, text: r.sample_names, mode: 'markers',
            marker: { size: 8, color: '#64ffda' }, type: 'scatter'
        }, {
            x: [Math.min(...r.y_cv), Math.max(...r.y_cv)], y: [0, 0],
            mode: 'lines', line: { color: '#666', dash: 'dash' }, showlegend: false
        }], {
            ...PLOTLY_LAYOUT, title: 'Residuals (CV)',
            xaxis: { ...PLOTLY_LAYOUT.xaxis, title: 'Predicted' },
            yaxis: { ...PLOTLY_LAYOUT.yaxis, title: 'Residual' }
        }, { responsive: true });
    }
}

// ====================== UTILS ======================
function setStatus(msg) { document.getElementById('status').textContent = msg; }

// Init on load
init();
</script>
</body>
</html>
```

- [ ] **Step 2: Start server and test manually**

Run: `cd ~/Desktop/nir-calibration && uvicorn app:app --reload --port 8000`
Open: `http://localhost:8000`
Expected: UI loads, example project shows 3 spectra, PCA and PLS tabs work.

- [ ] **Step 3: Commit**

```bash
git add static/index.html
git commit -m "feat: frontend SPA — spectra view, PCA, PLS with Plotly.js"
```

---

### Task 8: Integration test + final validation

**Files:**
- Create: `~/Desktop/nir-calibration/tests/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_integration.py
"""Test full pipeline: load → preprocess → PCA → PLS."""
import numpy as np
from pathlib import Path

EXAMPLE_DIR = Path(__file__).parent.parent / "projects" / "example"


def test_full_pipeline():
    from data_loader import load_project
    from preprocess import apply_pipeline
    from models import run_pca, run_pls

    # Load
    data = load_project(EXAMPLE_DIR)
    assert data["X"].shape[0] == 3

    # Preprocess
    pipeline = [{"method": "snv"}, {"method": "mean_center"}]
    X, wn = apply_pipeline(data["X"], data["wavenumbers"], pipeline)
    assert X.shape == data["X"].shape

    # PCA
    pca_result = run_pca(X, n_components=2)
    assert pca_result["scores"].shape == (3, 2)
    assert len(pca_result["explained_variance"]) == 2

    # PLS
    y = data["targets"]["procent_sa"]
    pls_result = run_pls(X, y, n_lv=2)
    assert "rmsec" in pls_result
    assert len(pls_result["y_cal"]) == 3


def test_api_endpoints():
    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)

    # List projects
    res = client.get("/api/projects")
    assert res.status_code == 200
    assert "example" in res.json()["projects"]

    # Get data
    res = client.get("/api/projects/example/data")
    assert res.status_code == 200
    d = res.json()
    assert len(d["sample_names"]) == 3
    assert "procent_sa" in d["targets"]

    # Preprocess
    res = client.post("/api/projects/example/preprocess",
                      json={"pipeline": [{"method": "snv"}]})
    assert res.status_code == 200
    assert len(res.json()["X"]) == 3

    # PCA
    res = client.post("/api/projects/example/pca",
                      json={"n_components": 2, "pipeline": []})
    assert res.status_code == 200
    assert len(res.json()["scores"]) == 3

    # PLS
    res = client.post("/api/projects/example/pls",
                      json={"target": "procent_sa", "n_lv": 2, "pipeline": []})
    assert res.status_code == 200
    assert "rmsec" in res.json()
```

- [ ] **Step 2: Run all tests**

Run: `cd ~/Desktop/nir-calibration && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: integration tests — full pipeline + API endpoints"
```

- [ ] **Step 4: Final run**

Run: `cd ~/Desktop/nir-calibration && uvicorn app:app --port 8000`
Verify in browser: spectra display, preprocessing modal, PCA (all 4 charts), PLS (all 4 charts + metrics).
