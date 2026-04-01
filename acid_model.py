"""
acid_model.py — OLS regression model for citric acid dosage prediction.

Reads feature table, filters to K7+K40GL, fits OLS with 4 features,
runs LOO-CV, generates HTML report with diagnostics.

Usage:
    python acid_model.py
"""

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.model_selection import LeaveOneOut
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import base64
from io import BytesIO
from pathlib import Path

FEATURE_CSV = Path("data/parquet/feature_table.csv")
MODEL_CSV = Path("data/parquet/model_data.csv")
OUT_HTML = Path("raport_model.html")

FEATURES = ["naoh_50_kg_per_ton", "delta_ph_czwart", "produkt_K40GL", "wielkosc_kg"]
TARGET = "acid_kg_per_ton"


def load_data() -> pd.DataFrame:
    """Load feature table, filter to K7+K40GL, create binary product column."""
    df = pd.read_csv(FEATURE_CSV)
    df = df[df["produkt"].isin(["Chegina K7", "Chegina K40GL"])].copy()
    df["produkt_K40GL"] = (df["produkt"] == "Chegina K40GL").astype(int)

    model_cols = FEATURES + [TARGET]
    before = len(df)
    df = df.dropna(subset=model_cols).reset_index(drop=True)
    print(f"Data: {before} batches, {len(df)} complete cases (dropped {before - len(df)})")

    export_cols = ["batch_id", "produkt", "nr_partii"] + FEATURES + [TARGET]
    df[export_cols].to_csv(MODEL_CSV, index=False)
    print(f"Model data saved: {MODEL_CSV}")

    return df


def check_vif(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Variance Inflation Factors. Drop features with VIF > 5."""
    from statsmodels.stats.outliers_influence import variance_inflation_factor

    X = df[FEATURES].values
    vif_data = []
    for i, feat in enumerate(FEATURES):
        vif_val = variance_inflation_factor(X, i)
        vif_data.append({"feature": feat, "VIF": round(vif_val, 2)})

    vif_df = pd.DataFrame(vif_data)
    print("\n=== VIF Check ===")
    print(vif_df.to_string(index=False))

    high_vif = vif_df[vif_df["VIF"] > 5]
    if not high_vif.empty:
        print(f"\nWARNING: High VIF detected: {high_vif['feature'].tolist()}")

    return vif_df


def fit_ols(df: pd.DataFrame):
    """Fit OLS regression with constant."""
    X = sm.add_constant(df[FEATURES])
    y = df[TARGET]

    model = sm.OLS(y, X).fit()

    print("\n=== OLS Regression Results ===")
    print(model.summary())

    print("\n=== Coefficients with 95% CI ===")
    conf = model.conf_int(alpha=0.05)
    coef_table = pd.DataFrame({
        "coefficient": model.params,
        "std_err": model.bse,
        "t_stat": model.tvalues,
        "p_value": model.pvalues,
        "ci_lower": conf[0],
        "ci_upper": conf[1],
    })
    print(coef_table.round(4).to_string())

    return model


def loo_cv(df: pd.DataFrame) -> tuple:
    """Leave-One-Out cross-validation. Returns predictions DataFrame."""
    X_full = sm.add_constant(df[FEATURES])
    y_full = df[TARGET].values

    loo = LeaveOneOut()
    predictions = []

    for train_idx, test_idx in loo.split(X_full):
        X_train, X_test = X_full.iloc[train_idx], X_full.iloc[test_idx]
        y_train = y_full[train_idx]

        model_fold = sm.OLS(y_train, X_train).fit()
        y_pred = model_fold.predict(X_test).iloc[0]

        predictions.append({
            "batch_id": df.iloc[test_idx[0]]["batch_id"],
            "produkt": df.iloc[test_idx[0]]["produkt"],
            "actual": y_full[test_idx[0]],
            "predicted_loo": y_pred,
            "residual_loo": y_full[test_idx[0]] - y_pred,
        })

    pred_df = pd.DataFrame(predictions)

    ss_res = (pred_df["residual_loo"] ** 2).sum()
    ss_tot = ((pred_df["actual"] - pred_df["actual"].mean()) ** 2).sum()
    loo_r2 = 1 - ss_res / ss_tot
    loo_mae = pred_df["residual_loo"].abs().mean()
    loo_rmse = np.sqrt((pred_df["residual_loo"] ** 2).mean())

    print("\n=== LOO-CV Results ===")
    print(f"  LOO R²:   {loo_r2:.3f}")
    print(f"  LOO MAE:  {loo_mae:.3f} kg/t")
    print(f"  LOO RMSE: {loo_rmse:.3f} kg/t")

    print("\n=== Predictions ===")
    print(pred_df.round(3).to_string(index=False))

    return pred_df, {"loo_r2": loo_r2, "loo_mae": loo_mae, "loo_rmse": loo_rmse}


def bootstrap_ci(df: pd.DataFrame, n_boot: int = 1000) -> pd.DataFrame:
    """Bootstrap confidence intervals for coefficients."""
    X = sm.add_constant(df[FEATURES])
    y = df[TARGET].values
    feat_names = ["const"] + FEATURES

    rng = np.random.RandomState(42)
    boot_coefs = []

    for _ in range(n_boot):
        idx = rng.choice(len(X), size=len(X), replace=True)
        X_b, y_b = X.iloc[idx], y[idx]
        try:
            m = sm.OLS(y_b, X_b).fit()
            boot_coefs.append(m.params.values)
        except Exception:
            continue

    boot_arr = np.array(boot_coefs)
    ci_df = pd.DataFrame({
        "feature": feat_names,
        "boot_mean": boot_arr.mean(axis=0),
        "boot_ci_2.5": np.percentile(boot_arr, 2.5, axis=0),
        "boot_ci_97.5": np.percentile(boot_arr, 97.5, axis=0),
    })

    print("\n=== Bootstrap CIs (1000 resamples) ===")
    print(ci_df.round(4).to_string(index=False))

    return ci_df


def diagnostics(model, df: pd.DataFrame, pred_df: pd.DataFrame) -> list:
    """Generate diagnostic plots. Returns list of (name, fig) tuples."""
    figs = []

    X = sm.add_constant(df[FEATURES])
    y = df[TARGET].values
    y_pred_insample = model.predict(X)
    residuals = model.resid

    # 1. Actual vs Predicted (LOO)
    fig, ax = plt.subplots(figsize=(8, 6))
    colors = {"Chegina K7": "#1f77b4", "Chegina K40GL": "#ff7f0e"}
    for prod, color in colors.items():
        mask = pred_df["produkt"] == prod
        ax.scatter(pred_df.loc[mask, "actual"], pred_df.loc[mask, "predicted_loo"],
                  c=color, label=prod, s=80, edgecolors="k", linewidth=0.5, zorder=3)
    lims = [min(y.min(), pred_df["predicted_loo"].min()) - 1,
            max(y.max(), pred_df["predicted_loo"].max()) + 1]
    ax.plot(lims, lims, "k--", alpha=0.5, label="Perfect prediction")
    ax.set_xlabel("Actual acid (kg/ton)")
    ax.set_ylabel("Predicted acid (kg/ton) — LOO")
    ax.set_title("Actual vs LOO-Predicted")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    figs.append(("actual_vs_predicted", fig))

    # 2. Residuals vs Fitted
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(y_pred_insample, residuals, s=60, edgecolors="k", linewidth=0.5)
    ax.axhline(y=0, color="red", linestyle="--", alpha=0.5)
    ax.set_xlabel("Fitted values")
    ax.set_ylabel("Residuals")
    ax.set_title("Residuals vs Fitted")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    figs.append(("residuals_vs_fitted", fig))

    # 3. Q-Q plot
    fig, ax = plt.subplots(figsize=(6, 6))
    stats.probplot(residuals, dist="norm", plot=ax)
    ax.set_title("Q-Q Plot of Residuals")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    figs.append(("qq_plot", fig))

    # 4. Cook's distance
    influence = model.get_influence()
    cooks_d = influence.cooks_distance[0]
    fig, ax = plt.subplots(figsize=(10, 5))
    batch_labels = df["batch_id"].str.replace("Chegina_", "").str.replace("__", " ")
    ax.bar(range(len(cooks_d)), cooks_d, color="#2196F3", edgecolor="k", linewidth=0.5)
    ax.set_xticks(range(len(cooks_d)))
    ax.set_xticklabels(batch_labels, rotation=45, ha="right", fontsize=8)
    ax.axhline(y=4/len(df), color="red", linestyle="--", alpha=0.5,
               label=f"Threshold (4/n = {4/len(df):.2f})")
    ax.set_ylabel("Cook's Distance")
    ax.set_title("Cook's Distance — Influential Observations")
    ax.legend()
    plt.tight_layout()
    figs.append(("cooks_distance", fig))

    threshold = 4 / len(df)
    influential = [(df.iloc[i]["batch_id"], round(d, 3)) for i, d in enumerate(cooks_d) if d > threshold]
    if influential:
        print(f"\n=== Influential observations (Cook's D > {threshold:.2f}) ===")
        for bid, d in influential:
            print(f"  {bid}: {d}")
    else:
        print(f"\nNo influential observations (all Cook's D < {threshold:.2f})")

    return figs


if __name__ == "__main__":
    print("=" * 60)
    print("Citric Acid Dosage — Prediction Model")
    print("=" * 60)

    print("\n[1/6] Loading data...")
    df = load_data()

    print("\n[2/6] VIF check...")
    vif_df = check_vif(df)

    print("\n[3/6] Fitting OLS...")
    model = fit_ols(df)

    print("\n[4/6] LOO cross-validation...")
    pred_df, loo_metrics = loo_cv(df)

    print("\n[5/6] Bootstrap CIs...")
    boot_ci_df = bootstrap_ci(df)

    print("\n[6/6] Diagnostics...")
    diag_figs = diagnostics(model, df, pred_df)
    for name, fig in diag_figs:
        fig.savefig(f"/tmp/{name}.png", dpi=100, bbox_inches="tight")

    print("\n" + "=" * 60)
    print(f"In-sample R²: {model.rsquared:.3f} | Adj R²: {model.rsquared_adj:.3f}")
    print(f"LOO-CV R²:    {loo_metrics['loo_r2']:.3f}")
    print(f"LOO MAE:      {loo_metrics['loo_mae']:.2f} kg/t")
    print(f"LOO RMSE:     {loo_metrics['loo_rmse']:.2f} kg/t")
