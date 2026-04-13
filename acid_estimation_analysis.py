"""
Acid estimation model for K7 chegina.

Compares two OLS models for predicting citric acid dosage (kg)
from batch mass and pH_start, with optional woda_refrakcja feature.

Usage:
    python acid_estimation_analysis.py
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.model_selection import LeaveOneOut


def load_data(csv_path: str) -> pd.DataFrame:
    """Load kwas.csv, fix Polish decimal commas, return clean DataFrame."""
    df = pd.read_csv(csv_path, sep=";", decimal=",")
    df = df.dropna(how="all")
    df.columns = ["masa_kg", "kwas_kg", "woda_kg", "ph_start", "ph_koniec"]
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(np.float64)
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


def run_loocv(df: pd.DataFrame, predictors: list[str]) -> dict:
    """Leave-One-Out CV. Returns MAE (in kg), MAPE (%), R² CV, residuals, predictions."""
    X = df[predictors].values
    y = df["kwas_per_ton"].values
    masa = df["masa_kg"].values
    loo = LeaveOneOut()

    pred_per_ton = np.zeros(len(y))
    for train_idx, test_idx in loo.split(X):
        X_train = sm.add_constant(X[train_idx])
        X_test = sm.add_constant(X[test_idx], has_constant=False)
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
