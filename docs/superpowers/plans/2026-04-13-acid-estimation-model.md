# Acid Estimation Model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Python script that trains and validates two linear regression models (baseline and extended) for estimating citric acid dosage in K7 chegina batches, outputting metrics, plots, and a recommendation.

**Architecture:** Single script `acid_estimation_analysis.py` at repo root. Reads `data/kwas.csv`, engineers features (kwas_per_ton, woda_refrakcja_per_ton), fits two OLS models via statsmodels, validates with LOOCV via scikit-learn, generates matplotlib plots, prints a comparison report with recommendation.

**Tech Stack:** Python 3.12, pandas, numpy, statsmodels, scikit-learn, matplotlib, scipy

---

### Task 1: Data loading and feature engineering

**Files:**
- Create: `acid_estimation_analysis.py`
- Create: `tests/test_acid_estimation.py`

- [ ] **Step 1: Write test for CSV loading and feature computation**

```python
# tests/test_acid_estimation.py
import pandas as pd
import numpy as np
import pytest


def make_sample_df():
    """Minimal sample matching kwas.csv structure."""
    return pd.DataFrame({
        "masa_kg": [12600, 8600, 7400],
        "kwas_kg": [100.0, 75.0, 63.0],
        "woda_kg": [915.0, 600.0, 530.0],
        "ph_start": [11.72, 11.77, 11.76],
        "ph_koniec": [6.2, 6.47, 6.04],
    })


def test_load_csv():
    from acid_estimation_analysis import load_data
    df = load_data("data/kwas.csv")
    assert len(df) == 45
    assert list(df.columns) == ["masa_kg", "kwas_kg", "woda_kg", "ph_start", "ph_koniec"]
    assert df["masa_kg"].dtype == np.float64
    assert df["ph_start"].dtype == np.float64


def test_feature_engineering():
    from acid_estimation_analysis import add_features
    df = make_sample_df()
    result = add_features(df)
    # kwas_per_ton = kwas_kg / (masa_kg / 1000)
    expected_kpt = [100.0 / 12.6, 75.0 / 8.6, 63.0 / 7.4]
    np.testing.assert_allclose(result["kwas_per_ton"].values, expected_kpt, rtol=1e-6)
    # woda_refrakcja = woda_kg - kwas_kg
    expected_wr = [815.0, 525.0, 467.0]
    np.testing.assert_allclose(result["woda_refrakcja"].values, expected_wr, rtol=1e-6)
    # woda_refrakcja_per_ton = woda_refrakcja / (masa_kg / 1000)
    expected_wrpt = [815.0 / 12.6, 525.0 / 8.6, 467.0 / 7.4]
    np.testing.assert_allclose(result["woda_refrakcja_per_ton"].values, expected_wrpt, rtol=1e-6)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_acid_estimation.py -v`
Expected: FAIL with "ModuleNotFoundError" or "cannot import name 'load_data'"

- [ ] **Step 3: Implement load_data and add_features**

```python
# acid_estimation_analysis.py
"""
Acid estimation model for K7 chegina.

Compares two OLS models for predicting citric acid dosage (kg)
from batch mass and pH_start, with optional woda_refrakcja feature.

Usage:
    python acid_estimation_analysis.py
"""

import numpy as np
import pandas as pd


def load_data(csv_path: str) -> pd.DataFrame:
    """Load kwas.csv, fix Polish decimal commas, return clean DataFrame."""
    df = pd.read_csv(csv_path, sep=";", decimal=",")
    df = df.dropna(how="all")
    df.columns = ["masa_kg", "kwas_kg", "woda_kg", "ph_start", "ph_koniec"]
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna()
    return df.reset_index(drop=True)


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add per-ton normalized features."""
    df = df.copy()
    tons = df["masa_kg"] / 1000.0
    df["kwas_per_ton"] = df["kwas_kg"] / tons
    df["woda_refrakcja"] = df["woda_kg"] - df["kwas_kg"]
    df["woda_refrakcja_per_ton"] = df["woda_refrakcja"] / tons
    return df
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_acid_estimation.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add acid_estimation_analysis.py tests/test_acid_estimation.py
git commit -m "feat: acid estimation — data loading and feature engineering"
```

---

### Task 2: OLS model fitting

**Files:**
- Modify: `acid_estimation_analysis.py`
- Modify: `tests/test_acid_estimation.py`

- [ ] **Step 1: Write test for model fitting**

Append to `tests/test_acid_estimation.py`:

```python
def test_fit_model_a():
    from acid_estimation_analysis import load_data, add_features, fit_model
    df = add_features(make_sample_df())
    result = fit_model(df, predictors=["ph_start"])
    assert "coefficients" in result
    assert "r_squared" in result
    assert "p_values" in result
    assert "model" in result
    assert len(result["coefficients"]) == 2  # const + ph_start


def test_fit_model_b():
    from acid_estimation_analysis import load_data, add_features, fit_model
    df = add_features(make_sample_df())
    result = fit_model(df, predictors=["ph_start", "woda_refrakcja_per_ton"])
    assert len(result["coefficients"]) == 3  # const + 2 predictors
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_acid_estimation.py::test_fit_model_a tests/test_acid_estimation.py::test_fit_model_b -v`
Expected: FAIL with "cannot import name 'fit_model'"

- [ ] **Step 3: Implement fit_model**

Add to `acid_estimation_analysis.py`:

```python
import statsmodels.api as sm


def fit_model(df: pd.DataFrame, predictors: list[str]) -> dict:
    """Fit OLS: kwas_per_ton ~ predictors. Returns coefficients, R², p-values, model."""
    X = sm.add_constant(df[predictors])
    y = df["kwas_per_ton"]
    model = sm.OLS(y, X).fit()
    return {
        "coefficients": model.params.to_dict(),
        "r_squared": model.rsquared,
        "r_squared_adj": model.rsquared_adj,
        "p_values": model.pvalues.to_dict(),
        "model": model,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_acid_estimation.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add acid_estimation_analysis.py tests/test_acid_estimation.py
git commit -m "feat: acid estimation — OLS model fitting with statsmodels"
```

---

### Task 3: LOOCV validation

**Files:**
- Modify: `acid_estimation_analysis.py`
- Modify: `tests/test_acid_estimation.py`

- [ ] **Step 1: Write test for LOOCV**

Append to `tests/test_acid_estimation.py`:

```python
def test_loocv():
    from acid_estimation_analysis import load_data, add_features, run_loocv
    df = load_data("data/kwas.csv")
    df = add_features(df)
    metrics = run_loocv(df, predictors=["ph_start"])
    assert "mae_kg" in metrics
    assert "mape_pct" in metrics
    assert "r2_cv" in metrics
    assert "residuals" in metrics
    assert "predictions" in metrics
    # MAE should be reasonable (not zero, not huge)
    assert 0 < metrics["mae_kg"] < 50
    assert 0 < metrics["mape_pct"] < 100
    assert len(metrics["residuals"]) == 45
    assert len(metrics["predictions"]) == 45
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_acid_estimation.py::test_loocv -v`
Expected: FAIL with "cannot import name 'run_loocv'"

- [ ] **Step 3: Implement run_loocv**

Add to `acid_estimation_analysis.py`:

```python
from sklearn.model_selection import LeaveOneOut


def run_loocv(df: pd.DataFrame, predictors: list[str]) -> dict:
    """Leave-One-Out CV. Returns MAE (in kg), MAPE (%), R² CV, residuals, predictions."""
    X = df[predictors].values
    y = df["kwas_per_ton"].values
    masa = df["masa_kg"].values
    loo = LeaveOneOut()

    pred_per_ton = np.zeros(len(y))
    for train_idx, test_idx in loo.split(X):
        X_train = sm.add_constant(X[train_idx])
        X_test = sm.add_constant(X[test_idx])
        model = sm.OLS(y[train_idx], X_train).fit()
        pred_per_ton[test_idx] = model.predict(X_test)

    pred_kg = pred_per_ton * masa / 1000.0
    actual_kg = y * masa / 1000.0
    residuals_kg = actual_kg - pred_kg

    mae = np.mean(np.abs(residuals_kg))
    mape = np.mean(np.abs(residuals_kg / actual_kg)) * 100.0

    ss_res = np.sum(residuals_kg ** 2)
    ss_tot = np.sum((actual_kg - np.mean(actual_kg)) ** 2)
    r2_cv = 1.0 - ss_res / ss_tot

    return {
        "mae_kg": mae,
        "mape_pct": mape,
        "r2_cv": r2_cv,
        "residuals": residuals_kg,
        "predictions": pred_kg,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_acid_estimation.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add acid_estimation_analysis.py tests/test_acid_estimation.py
git commit -m "feat: acid estimation — LOOCV validation with MAE/MAPE/R²"
```

---

### Task 4: Model comparison logic

**Files:**
- Modify: `acid_estimation_analysis.py`
- Modify: `tests/test_acid_estimation.py`

- [ ] **Step 1: Write test for model comparison**

Append to `tests/test_acid_estimation.py`:

```python
def test_compare_models():
    from acid_estimation_analysis import load_data, add_features, fit_model, run_loocv, compare_models

    df = load_data("data/kwas.csv")
    df = add_features(df)

    fit_a = fit_model(df, predictors=["ph_start"])
    cv_a = run_loocv(df, predictors=["ph_start"])

    fit_b = fit_model(df, predictors=["ph_start", "woda_refrakcja_per_ton"])
    cv_b = run_loocv(df, predictors=["ph_start", "woda_refrakcja_per_ton"])

    result = compare_models(fit_a, cv_a, fit_b, cv_b)
    assert result["winner"] in ("A", "B")
    assert "reasons" in result
    assert isinstance(result["reasons"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_acid_estimation.py::test_compare_models -v`
Expected: FAIL with "cannot import name 'compare_models'"

- [ ] **Step 3: Implement compare_models**

Add to `acid_estimation_analysis.py`:

```python
def compare_models(fit_a: dict, cv_a: dict, fit_b: dict, cv_b: dict) -> dict:
    """Compare Model A vs B. B wins if woda_refrakcja is significant, MAE drops >5%, R² improves."""
    reasons = []
    b_wins = 0

    # Criterion 1: woda_refrakcja_per_ton p-value < 0.05
    p_woda = fit_b["p_values"].get("woda_refrakcja_per_ton", 1.0)
    if p_woda < 0.05:
        reasons.append(f"woda_refrakcja_per_ton significant (p={p_woda:.4f})")
        b_wins += 1
    else:
        reasons.append(f"woda_refrakcja_per_ton NOT significant (p={p_woda:.4f})")

    # Criterion 2: MAE drops >5%
    mae_drop_pct = (cv_a["mae_kg"] - cv_b["mae_kg"]) / cv_a["mae_kg"] * 100.0
    if mae_drop_pct > 5.0:
        reasons.append(f"MAE dropped {mae_drop_pct:.1f}% (A={cv_a['mae_kg']:.2f}, B={cv_b['mae_kg']:.2f})")
        b_wins += 1
    else:
        reasons.append(f"MAE drop insufficient: {mae_drop_pct:.1f}% (A={cv_a['mae_kg']:.2f}, B={cv_b['mae_kg']:.2f})")

    # Criterion 3: R² CV improves
    if cv_b["r2_cv"] > cv_a["r2_cv"]:
        reasons.append(f"R² CV improved (A={cv_a['r2_cv']:.4f}, B={cv_b['r2_cv']:.4f})")
        b_wins += 1
    else:
        reasons.append(f"R² CV did not improve (A={cv_a['r2_cv']:.4f}, B={cv_b['r2_cv']:.4f})")

    winner = "B" if b_wins >= 2 else "A"
    reasons.append(f"Winner: Model {'B (extended)' if winner == 'B' else 'A (baseline)'} ({b_wins}/3 criteria met)")

    return {"winner": winner, "reasons": reasons}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_acid_estimation.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add acid_estimation_analysis.py tests/test_acid_estimation.py
git commit -m "feat: acid estimation — model comparison logic (A vs B)"
```

---

### Task 5: Plotting functions

**Files:**
- Modify: `acid_estimation_analysis.py`
- Modify: `tests/test_acid_estimation.py`

- [ ] **Step 1: Write test for plot generation**

Append to `tests/test_acid_estimation.py`:

```python
import os

def test_generate_plots():
    from acid_estimation_analysis import load_data, add_features, fit_model, run_loocv, generate_plots
    df = load_data("data/kwas.csv")
    df = add_features(df)
    fit_a = fit_model(df, predictors=["ph_start"])
    cv_a = run_loocv(df, predictors=["ph_start"])

    out_dir = "test_plots_output"
    generate_plots(df, fit_a, cv_a, predictors=["ph_start"], label="Model_A", out_dir=out_dir)

    expected_files = [
        f"{out_dir}/Model_A_scatter_regression.png",
        f"{out_dir}/Model_A_pred_vs_actual.png",
        f"{out_dir}/Model_A_residuals_vs_masa.png",
        f"{out_dir}/Model_A_residuals_vs_fitted.png",
    ]
    for f in expected_files:
        assert os.path.exists(f), f"Missing plot: {f}"
        os.remove(f)
    os.rmdir(out_dir)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_acid_estimation.py::test_generate_plots -v`
Expected: FAIL with "cannot import name 'generate_plots'"

- [ ] **Step 3: Implement generate_plots**

Add to `acid_estimation_analysis.py`:

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path


def generate_plots(
    df: pd.DataFrame, fit_result: dict, cv_result: dict,
    predictors: list[str], label: str, out_dir: str = "plots"
) -> list[str]:
    """Generate 4 diagnostic plots. Returns list of saved file paths."""
    Path(out_dir).mkdir(exist_ok=True)
    paths = []
    model = fit_result["model"]
    masa = df["masa_kg"].values
    actual_kg = df["kwas_kg"].values
    pred_kg = cv_result["predictions"]
    residuals_kg = cv_result["residuals"]

    # 1. Scatter: kwas_per_ton vs pH_start with regression line
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(df["ph_start"], df["kwas_per_ton"], alpha=0.7, edgecolors="k", linewidths=0.5)
    ph_range = np.linspace(df["ph_start"].min(), df["ph_start"].max(), 100)
    if len(predictors) == 1:
        X_plot = sm.add_constant(ph_range)
        ax.plot(ph_range, model.predict(X_plot), "r-", linewidth=2)
    ax.set_xlabel("pH start")
    ax.set_ylabel("Kwas cytrynowy [kg/tonę]")
    ax.set_title(f"{label}: kwas/tonę vs pH start")
    ax.grid(True, alpha=0.3)
    p = f"{out_dir}/{label}_scatter_regression.png"
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    paths.append(p)

    # 2. Prediction vs actual (kg)
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(actual_kg, pred_kg, alpha=0.7, edgecolors="k", linewidths=0.5)
    lims = [min(actual_kg.min(), pred_kg.min()) - 5, max(actual_kg.max(), pred_kg.max()) + 5]
    ax.plot(lims, lims, "r--", linewidth=1)
    ax.set_xlabel("Rzeczywisty kwas [kg]")
    ax.set_ylabel("Predykcja kwas [kg]")
    ax.set_title(f"{label}: predykcja vs rzeczywistość")
    ax.set_xlim(lims)
    ax.set_ylim(lims)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    p = f"{out_dir}/{label}_pred_vs_actual.png"
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    paths.append(p)

    # 3. Residuals vs masa (normalization check)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(masa, residuals_kg, alpha=0.7, edgecolors="k", linewidths=0.5)
    ax.axhline(0, color="r", linestyle="--", linewidth=1)
    ax.set_xlabel("Masa szarży [kg]")
    ax.set_ylabel("Residuum [kg]")
    ax.set_title(f"{label}: residua vs masa (test normalizacji)")
    ax.grid(True, alpha=0.3)
    p = f"{out_dir}/{label}_residuals_vs_masa.png"
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    paths.append(p)

    # 4. Residuals vs fitted
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(pred_kg, residuals_kg, alpha=0.7, edgecolors="k", linewidths=0.5)
    ax.axhline(0, color="r", linestyle="--", linewidth=1)
    ax.set_xlabel("Fitted [kg]")
    ax.set_ylabel("Residuum [kg]")
    ax.set_title(f"{label}: residua vs fitted")
    ax.grid(True, alpha=0.3)
    p = f"{out_dir}/{label}_residuals_vs_fitted.png"
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    paths.append(p)

    return paths
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_acid_estimation.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add acid_estimation_analysis.py tests/test_acid_estimation.py
git commit -m "feat: acid estimation — diagnostic plots (4 charts per model)"
```

---

### Task 6: Main report runner

**Files:**
- Modify: `acid_estimation_analysis.py`

- [ ] **Step 1: Write test for main report**

Append to `tests/test_acid_estimation.py`:

```python
def test_main_report(capsys):
    from acid_estimation_analysis import main
    main(out_dir="test_report_output")
    captured = capsys.readouterr()
    assert "Model A" in captured.out
    assert "Model B" in captured.out
    assert "MAE" in captured.out
    assert "Winner" in captured.out or "Rekomendacja" in captured.out
    # Cleanup plot files
    import shutil
    if os.path.exists("test_report_output"):
        shutil.rmtree("test_report_output")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_acid_estimation.py::test_main_report -v`
Expected: FAIL with "cannot import name 'main'"

- [ ] **Step 3: Implement main()**

Add to `acid_estimation_analysis.py`:

```python
def print_model_summary(name: str, fit_result: dict, cv_result: dict):
    """Print model coefficients, significance, and CV metrics."""
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    print(f"\nWspółczynniki:")
    for k, v in fit_result["coefficients"].items():
        p = fit_result["p_values"][k]
        sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
        print(f"  {k:>30s} = {v:>10.4f}  (p={p:.4f}) {sig}")
    print(f"\n  R² (train)  = {fit_result['r_squared']:.4f}")
    print(f"  R² adj      = {fit_result['r_squared_adj']:.4f}")
    print(f"\nWalidacja LOOCV:")
    print(f"  MAE         = {cv_result['mae_kg']:.2f} kg")
    print(f"  MAPE        = {cv_result['mape_pct']:.1f}%")
    print(f"  R² (CV)     = {cv_result['r2_cv']:.4f}")


def main(out_dir: str = "plots_acid_estimation"):
    """Run full analysis: load data, fit both models, validate, compare, plot."""
    df = load_data("data/kwas.csv")
    df = add_features(df)
    print(f"Załadowano {len(df)} obserwacji z data/kwas.csv")
    print(f"Masy szarż: {sorted(df['masa_kg'].unique())}")

    # Model A: kwas_per_ton ~ pH_start
    fit_a = fit_model(df, predictors=["ph_start"])
    cv_a = run_loocv(df, predictors=["ph_start"])
    print_model_summary("Model A: kwas_per_ton ~ pH_start", fit_a, cv_a)

    # Model B: kwas_per_ton ~ pH_start + woda_refrakcja_per_ton
    fit_b = fit_model(df, predictors=["ph_start", "woda_refrakcja_per_ton"])
    cv_b = run_loocv(df, predictors=["ph_start", "woda_refrakcja_per_ton"])
    print_model_summary("Model B: kwas_per_ton ~ pH_start + woda_refrakcja_per_ton", fit_b, cv_b)

    # Compare
    comparison = compare_models(fit_a, cv_a, fit_b, cv_b)
    print(f"\n{'='*60}")
    print(f"  Porównanie modeli")
    print(f"{'='*60}")
    for r in comparison["reasons"]:
        print(f"  • {r}")
    print(f"\n  Rekomendacja: Model {comparison['winner']}")

    # Prediction example
    winner_predictors = ["ph_start"] if comparison["winner"] == "A" else ["ph_start", "woda_refrakcja_per_ton"]
    winner_fit = fit_a if comparison["winner"] == "A" else fit_b
    print(f"\n{'='*60}")
    print(f"  Przykład predykcji (zwycięski model)")
    print(f"{'='*60}")
    for masa in [7400, 8600, 12600]:
        coefs = winner_fit["coefficients"]
        kwas_pt = coefs["const"] + coefs["ph_start"] * 11.70
        if "woda_refrakcja_per_ton" in coefs:
            kwas_pt += coefs["woda_refrakcja_per_ton"] * 65.0  # typical value
        kwas_kg = kwas_pt * masa / 1000.0
        print(f"  masa={masa} kg, pH=11.70 → kwas ≈ {kwas_kg:.1f} kg")

    # Plots
    generate_plots(df, fit_a, cv_a, ["ph_start"], "Model_A", out_dir)
    generate_plots(df, fit_b, cv_b, ["ph_start", "woda_refrakcja_per_ton"], "Model_B", out_dir)
    print(f"\nWykresy zapisane do {out_dir}/")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_acid_estimation.py -v`
Expected: 8 passed

- [ ] **Step 5: Run the script end-to-end**

Run: `python acid_estimation_analysis.py`
Expected: Full report printed to stdout, plots saved to `plots_acid_estimation/`

- [ ] **Step 6: Commit**

```bash
git add acid_estimation_analysis.py tests/test_acid_estimation.py
git commit -m "feat: acid estimation — full report with comparison and plots"
```
