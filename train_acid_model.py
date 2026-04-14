#!/usr/bin/env python3
"""
train_acid_model.py — Train and compare acid dosage models for K7.

Target: kwas_per_kg_per_dpH = kwas_kg / (masa_kg + woda_kg - kwas_kg) / (pH_start - pH_end)
        i.e. kg acid per kg effective mass per unit pH change.

Then: dawka = model_predict(features) * masa_eff * delta_pH

Models compared:
  1. Linear regression (pH_start only)
  2. Polynomial deg=2 (pH_start)
  3. Polynomial deg=3 (pH_start)
  4. Linear on (pH_start, masa_kg)
  5. Poly2 on (pH_start, masa_kg)
  6. KNN (k=3, 5, 7)
  7. Ridge poly2

Output: coefficients for the best model, ready to embed in JS.
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.preprocessing import PolynomialFeatures
from sklearn.neighbors import KNeighborsRegressor
from sklearn.model_selection import LeaveOneOut
from sklearn.metrics import mean_absolute_error, mean_squared_error
import json


def load_data():
    df = pd.read_csv("data/kwas.csv", sep=";", decimal=",")
    df.columns = ["masa_kg", "kwas_kg", "woda_kg", "ph_start", "ph_end"]
    df = df.dropna()

    # Target: kwas per kg effective mass per unit pH drop
    df["masa_eff"] = df["masa_kg"] + df["woda_kg"] - df["kwas_kg"]
    df["delta_ph"] = df["ph_start"] - df["ph_end"]
    df["kwas_per_kg_per_dph"] = df["kwas_kg"] / df["masa_eff"] / df["delta_ph"]

    # Also compute buffer_cap = kwas_kg / delta_ph / (masa_eff/1000)
    df["buffer_cap"] = df["kwas_kg"] / df["delta_ph"] / (df["masa_eff"] / 1000)

    return df


def loo_evaluate(X, y, model_factory, name):
    """Leave-one-out cross-validation."""
    loo = LeaveOneOut()
    preds = np.empty(len(y))
    for train_idx, test_idx in loo.split(X):
        model = model_factory()
        model.fit(X[train_idx], y[train_idx])
        preds[test_idx] = model.predict(X[test_idx])

    residuals = y - preds
    mae = np.mean(np.abs(residuals))
    rmse = np.sqrt(np.mean(residuals**2))

    # Back-calculate actual acid prediction error (in kg)
    return {
        "name": name,
        "mae_target": mae,
        "rmse_target": rmse,
        "preds": preds,
    }


def main():
    df = load_data()
    print(f"Loaded {len(df)} observations")
    print(f"\nTarget stats (kwas_per_kg_per_dph):")
    print(f"  mean={df['kwas_per_kg_per_dph'].mean():.6f}")
    print(f"  std={df['kwas_per_kg_per_dph'].std():.6f}")
    print(f"  min={df['kwas_per_kg_per_dph'].min():.6f}")
    print(f"  max={df['kwas_per_kg_per_dph'].max():.6f}")

    y = df["kwas_per_kg_per_dph"].values
    ph = df["ph_start"].values.reshape(-1, 1)
    masa = df["masa_kg"].values.reshape(-1, 1)
    ph_masa = np.column_stack([ph.ravel(), masa.ravel()])

    results = []

    # 1. Constant (mean)
    mean_val = y.mean()
    preds_const = np.full(len(y), mean_val)
    res_const = y - preds_const
    results.append({
        "name": "Constant (mean)",
        "mae_target": np.mean(np.abs(res_const)),
        "rmse_target": np.sqrt(np.mean(res_const**2)),
        "preds": preds_const,
    })

    # 2. Linear on pH
    results.append(loo_evaluate(ph, y, LinearRegression, "Linear(pH)"))

    # 3. Poly2 on pH
    poly2 = PolynomialFeatures(2, include_bias=False)
    X_poly2 = poly2.fit_transform(ph)
    results.append(loo_evaluate(X_poly2, y, LinearRegression, "Poly2(pH)"))

    # 4. Poly3 on pH
    poly3 = PolynomialFeatures(3, include_bias=False)
    X_poly3 = poly3.fit_transform(ph)
    results.append(loo_evaluate(X_poly3, y, LinearRegression, "Poly3(pH)"))

    # 5. Linear on (pH, masa)
    results.append(loo_evaluate(ph_masa, y, LinearRegression, "Linear(pH, masa)"))

    # 6. Poly2 on (pH, masa)
    poly2_2d = PolynomialFeatures(2, include_bias=False)
    X_poly2_2d = poly2_2d.fit_transform(ph_masa)
    results.append(loo_evaluate(X_poly2_2d, y, LinearRegression, "Poly2(pH, masa)"))

    # 7. KNN k=3
    results.append(loo_evaluate(ph, y, lambda: KNeighborsRegressor(n_neighbors=3), "KNN(k=3, pH)"))

    # 8. KNN k=5
    results.append(loo_evaluate(ph, y, lambda: KNeighborsRegressor(n_neighbors=5), "KNN(k=5, pH)"))

    # 9. KNN k=7
    results.append(loo_evaluate(ph, y, lambda: KNeighborsRegressor(n_neighbors=7), "KNN(k=7, pH)"))

    # 10. Ridge Poly2 on pH
    results.append(loo_evaluate(X_poly2, y, lambda: Ridge(alpha=1.0), "Ridge Poly2(pH)"))

    # 11. KNN on (pH, masa) — normalized
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    ph_masa_scaled = scaler.fit_transform(ph_masa)

    def knn_scaled_factory():
        return KNeighborsRegressor(n_neighbors=5)

    # Manual LOO for scaled
    loo = LeaveOneOut()
    preds_knn_2d = np.empty(len(y))
    for train_idx, test_idx in loo.split(ph_masa_scaled):
        sc = StandardScaler()
        X_tr = sc.fit_transform(ph_masa[train_idx])
        X_te = sc.transform(ph_masa[test_idx])
        m = KNeighborsRegressor(n_neighbors=5)
        m.fit(X_tr, y[train_idx])
        preds_knn_2d[test_idx] = m.predict(X_te)
    res_knn_2d = y - preds_knn_2d
    results.append({
        "name": "KNN(k=5, pH+masa, scaled)",
        "mae_target": np.mean(np.abs(res_knn_2d)),
        "rmse_target": np.sqrt(np.mean(res_knn_2d**2)),
        "preds": preds_knn_2d,
    })

    # ── Results ──
    print("\n" + "=" * 70)
    print(f"{'Model':<30} {'MAE (target)':>14} {'RMSE (target)':>14}")
    print("-" * 70)
    for r in sorted(results, key=lambda x: x["mae_target"]):
        print(f"{r['name']:<30} {r['mae_target']:>14.6f} {r['rmse_target']:>14.6f}")

    # ── Back-calculate prediction error in kg ──
    print("\n" + "=" * 70)
    print("Back-calculated acid kg prediction error (LOO-CV):")
    print(f"{'Model':<30} {'MAE [kg]':>10} {'RMSE [kg]':>10} {'MAPE [%]':>10}")
    print("-" * 70)
    for r in sorted(results, key=lambda x: x["mae_target"]):
        # dawka_pred = pred * masa_eff * delta_ph
        dawka_pred = r["preds"] * df["masa_eff"].values * df["delta_ph"].values
        dawka_actual = df["kwas_kg"].values
        kg_errors = np.abs(dawka_pred - dawka_actual)
        mae_kg = np.mean(kg_errors)
        rmse_kg = np.sqrt(np.mean((dawka_pred - dawka_actual)**2))
        mape = np.mean(kg_errors / dawka_actual) * 100
        print(f"{r['name']:<30} {mae_kg:>10.2f} {rmse_kg:>10.2f} {mape:>10.1f}")
        r["mae_kg"] = mae_kg
        r["mape"] = mape

    # ── Best model details ──
    best = min(results, key=lambda x: x["mae_kg"])
    print(f"\n>>> Best model: {best['name']} (MAE={best['mae_kg']:.2f} kg, MAPE={best['mape']:.1f}%)")

    # ── Fit final model on all data and print coefficients ──
    print("\n" + "=" * 70)
    print("Final model coefficients (fit on all data):")

    # Constant
    print(f"\nConstant: mean = {y.mean():.6f}")

    # Linear(pH)
    m = LinearRegression().fit(ph, y)
    print(f"\nLinear(pH): intercept={m.intercept_:.6f}, coef_ph={m.coef_[0]:.8f}")

    # Poly2(pH)
    m2 = LinearRegression().fit(X_poly2, y)
    print(f"\nPoly2(pH): intercept={m2.intercept_:.6f}, coef_ph={m2.coef_[0]:.8f}, coef_ph2={m2.coef_[1]:.10f}")

    # Linear(pH, masa)
    m3 = LinearRegression().fit(ph_masa, y)
    print(f"\nLinear(pH, masa): intercept={m3.intercept_:.6f}, coef_ph={m3.coef_[0]:.8f}, coef_masa={m3.coef_[1]:.12f}")

    # Poly2(pH, masa)
    m4 = LinearRegression().fit(X_poly2_2d, y)
    feat_names = poly2_2d.get_feature_names_out(["ph", "masa"])
    print(f"\nPoly2(pH, masa): intercept={m4.intercept_:.6f}")
    for name, coef in zip(feat_names, m4.coef_):
        print(f"  {name}: {coef:.12f}")

    # ── JS-ready output for the best polynomial model ──
    print("\n" + "=" * 70)
    print("JS-ready coefficients:")
    print(f"""
// Model: target = kwas_kg / masa_eff / delta_pH
// Prediction: kwas_kg = coef * masa_eff_kg * (pH_start - pH_target)

// Constant model:
var ACID_COEF = {y.mean():.6f};
// dawka = ACID_COEF * masa_eff_kg * (pH_start - pH_target)

// Linear(pH) model:
// coef = {m.intercept_:.6f} + {m.coef_[0]:.8f} * pH_start
// dawka = coef * masa_eff_kg * (pH_start - pH_target)

// Poly2(pH) model:
// coef = {m2.intercept_:.6f} + {m2.coef_[0]:.8f} * pH + {m2.coef_[1]:.10f} * pH^2
// dawka = coef * masa_eff_kg * (pH_start - pH_target)
""")


if __name__ == "__main__":
    main()
