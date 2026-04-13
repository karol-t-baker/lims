"""
Acid estimation model for K7 chegina.

Compares two OLS models for predicting citric acid dosage (kg)
from batch mass and pH_start, with optional woda_refrakcja feature.

Usage:
    python acid_estimation_analysis.py
"""

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
