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

FEATURES = ["delta_ph_czwart", "wielkosc_kg"]
TARGET = "acid_kg_per_ton"


def load_data() -> pd.DataFrame:
    """Load feature table, filter to K7+K40GL."""
    df = pd.read_csv(FEATURE_CSV)
    df = df[df["produkt"].isin(["Chegina K7", "Chegina K40GL"])].copy()

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


def fig_to_base64(fig) -> str:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def generate_report(
    df: pd.DataFrame,
    model,
    vif_df: pd.DataFrame,
    pred_df: pd.DataFrame,
    loo_metrics: dict,
    boot_ci_df: pd.DataFrame,
    diag_figs: list,
):
    """Generate self-contained HTML report."""

    # Coefficient table
    conf = model.conf_int(alpha=0.05)
    coef_rows = ""
    for name in model.params.index:
        c = model.params[name]
        se = model.bse[name]
        t = model.tvalues[name]
        p = model.pvalues[name]
        lo, hi = conf.loc[name, 0], conf.loc[name, 1]
        p_str = f"{p:.4f}" if p >= 0.001 else f"{p:.2e}"
        sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
        coef_rows += f"<tr><td>{name}</td><td>{c:.4f}</td><td>{se:.4f}</td><td>{t:.2f}</td><td>{p_str} {sig}</td><td>[{lo:.4f}, {hi:.4f}]</td></tr>\n"

    # VIF table
    vif_rows = ""
    for _, r in vif_df.iterrows():
        color = "color:red" if r["VIF"] > 5 else ""
        vif_rows += f'<tr><td>{r["feature"]}</td><td style="{color}">{r["VIF"]:.2f}</td></tr>\n'

    # Predictions table
    pred_rows = ""
    for _, r in pred_df.iterrows():
        color = "color:red" if abs(r["residual_loo"]) > 2 * loo_metrics["loo_rmse"] else ""
        pred_rows += f'<tr><td>{r["batch_id"]}</td><td>{r["produkt"]}</td><td>{r["actual"]:.2f}</td><td>{r["predicted_loo"]:.2f}</td><td style="{color}">{r["residual_loo"]:.2f}</td></tr>\n'

    # Figures
    fig_html = ""
    for name, fig in diag_figs:
        b64 = fig_to_base64(fig)
        fig_html += f'<div class="chart"><img src="data:image/png;base64,{b64}" alt="{name}"></div>\n'

    # Operator formula
    params = model.params
    formula_parts = [f"{params['const']:.2f}"]
    for f in FEATURES:
        sign = "+" if params[f] >= 0 else "-"
        formula_parts.append(f"{sign} {abs(params[f]):.4f} x {f}")
    formula_str = " ".join(formula_parts)

    # Example calculation
    example_row = df[df["produkt"] == "Chegina K7"].iloc[0]
    example_pred = model.predict(sm.add_constant(example_row[FEATURES].to_frame().T, has_constant="add")).iloc[0]
    example_calc = f"""
    <p><strong>Przyklad:</strong> batch {example_row['batch_id']}</p>
    <ul>
        <li>delta_ph_czwart = {example_row['delta_ph_czwart']:.2f}</li>
        <li>wielkosc_kg = {example_row['wielkosc_kg']:.0f}</li>
    </ul>
    <p>Predykcja: <strong>{example_pred:.2f} kg/t</strong>
       (rzeczywista: {example_row[TARGET]:.2f} kg/t)</p>
    """

    # Feature ranges
    range_rows = ""
    for f in FEATURES:
        range_rows += f"<tr><td>{f}</td><td>{df[f].min():.2f}</td><td>{df[f].max():.2f}</td><td>{df[f].mean():.2f}</td></tr>\n"

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<title>Model Predykcji Dawki Kwasu Cytrynowego</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f5f5; }}
    h1 {{ color: #1a237e; border-bottom: 3px solid #1a237e; padding-bottom: 10px; }}
    h2 {{ color: #283593; margin-top: 40px; }}
    .summary {{ background: white; border-radius: 8px; padding: 20px; margin: 20px 0;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
    .summary .stat {{ display: inline-block; margin: 10px 20px; text-align: center; }}
    .summary .stat .value {{ font-size: 28px; font-weight: bold; color: #1a237e; }}
    .summary .stat .label {{ font-size: 12px; color: #666; }}
    .formula {{ background: #e8eaf6; border-radius: 8px; padding: 20px; margin: 20px 0;
                font-family: 'Courier New', monospace; font-size: 14px; }}
    .table {{ border-collapse: collapse; width: 100%; margin: 15px 0; font-size: 13px; }}
    .table th {{ background: #283593; color: white; padding: 8px 12px; text-align: left; }}
    .table td {{ padding: 6px 12px; border-bottom: 1px solid #e0e0e0; }}
    .table tr:hover {{ background: #e3f2fd; }}
    .chart {{ background: white; border-radius: 8px; padding: 15px; margin: 20px 0;
              box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center; }}
    .chart img {{ max-width: 100%; height: auto; }}
    .note {{ background: #fff3e0; border-left: 4px solid #ff9800;
             padding: 10px 15px; margin: 10px 0; font-size: 13px; }}
    .operator {{ background: #e8f5e9; border: 2px solid #4caf50; border-radius: 8px;
                 padding: 20px; margin: 20px 0; }}
    .operator h2 {{ color: #2e7d32; margin-top: 0; }}
</style>
</head>
<body>

<h1>Model Predykcji Dawki Kwasu Cytrynowego</h1>
<p>Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')} | Dane: {len(df)} szarzy (K7 + K40GL) | 2 cechy</p>

<div class="summary">
    <div class="stat"><div class="value">{model.rsquared:.3f}</div><div class="label">R\u00b2 (in-sample)</div></div>
    <div class="stat"><div class="value">{model.rsquared_adj:.3f}</div><div class="label">Adj R\u00b2</div></div>
    <div class="stat"><div class="value">{loo_metrics['loo_r2']:.3f}</div><div class="label">R\u00b2 (LOO-CV)</div></div>
    <div class="stat"><div class="value">{loo_metrics['loo_mae']:.2f}</div><div class="label">MAE (kg/t)</div></div>
    <div class="stat"><div class="value">{loo_metrics['loo_rmse']:.2f}</div><div class="label">RMSE (kg/t)</div></div>
</div>

<div class="note">
    <strong>Uwaga:</strong> n={len(df)} \u2014 model eksploracyjny. LOO R\u00b2 jest uczciw\u0105 metryk\u0105 generalizacji.
    Walidacja na nowych szarzach wymagana przed u\u017cyciem operacyjnym.
    \u015bredni b\u0142\u0105d predykcji (MAE): {loo_metrics['loo_mae']:.2f} kg/t.
</div>

<h2>Wz\u00f3r modelu</h2>
<div class="formula">
    acid_kg_per_ton = {formula_str}
</div>

<h2>Wsp\u00f3\u0142czynniki</h2>
<table class="table">
    <tr><th>Cecha</th><th>Wsp\u00f3\u0142czynnik</th><th>Std Error</th><th>t-stat</th><th>p-value</th><th>95% CI</th></tr>
    {coef_rows}
</table>

<h2>VIF (Variance Inflation Factor)</h2>
<p>Wszystkie VIF &lt; 5 = brak multikolinearno\u015bci.</p>
<table class="table">
    <tr><th>Cecha</th><th>VIF</th></tr>
    {vif_rows}
</table>

<h2>Predykcje LOO-CV</h2>
<table class="table">
    <tr><th>Szar\u017ca</th><th>Produkt</th><th>Rzeczywista (kg/t)</th><th>Predykcja LOO (kg/t)</th><th>Residual</th></tr>
    {pred_rows}
</table>

<h2>Diagnostyka</h2>
{fig_html}

<div class="operator">
    <h2>Dla operatora \u2014 Kalkulacja dawki</h2>
    <div class="formula">{formula_str}</div>
    <p><strong>Gdzie:</strong></p>
    <ul>
        <li><strong>delta_ph_czwart</strong> \u2014 r\u00f3\u017cnica mi\u0119dzy ostatnim a pierwszym pH 10% w czwartorz\u0119dowaniu</li>
        <li><strong>wielkosc_kg</strong> \u2014 wielko\u015b\u0107 szar\u017cy w kg</li>
    </ul>
    <p><strong>Zakresy danych treningowych:</strong></p>
    <table class="table">
        <tr><th>Cecha</th><th>Min</th><th>Max</th><th>\u015brednia</th></tr>
        {range_rows}
    </table>
    {example_calc}
    <p class="note"><strong>Uwaga:</strong> Model wa\u017cny tylko w zakresach danych treningowych.
    Predykcje poza zakresem mog\u0105 by\u0107 niedok\u0142adne. \u015bredni b\u0142\u0105d (MAE): \u00b1{loo_metrics['loo_mae']:.2f} kg/t.</p>
</div>

</body>
</html>"""

    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"\nHTML report saved: {OUT_HTML}")


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

    print("\n[6/6] Diagnostics + HTML report...")
    diag_figs = diagnostics(model, df, pred_df)
    generate_report(df, model, vif_df, pred_df, loo_metrics, boot_ci_df, diag_figs)

    print("\n" + "=" * 60)
    print(f"In-sample R\u00b2: {model.rsquared:.3f} | Adj R\u00b2: {model.rsquared_adj:.3f}")
    print(f"LOO-CV R\u00b2:    {loo_metrics['loo_r2']:.3f}")
    print(f"LOO MAE:      {loo_metrics['loo_mae']:.2f} kg/t")
    print(f"LOO RMSE:     {loo_metrics['loo_rmse']:.2f} kg/t")
    print(f"\nDone! Open {OUT_HTML} in browser.")
