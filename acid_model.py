"""
acid_model.py — Buffer capacity model for citric acid dosage prediction.

Reads verified JSONs directly, models buffer capacity (kg acid / ton / pH unit),
produces HTML report with operator formula.

Usage:
    python acid_model.py
"""

import json
import warnings
from itertools import combinations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor
from sklearn.model_selection import LeaveOneOut
from scipy import stats
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import base64
from io import BytesIO
from pathlib import Path

VERIFIED_DIR = Path("data/verified")
MODEL_CSV = Path("data/parquet/model_data.csv")
OUT_HTML = Path("raport_model.html")
TARGET = "buffer_cap"

ALL_FEATURES = ["wielkosc_kg", "ph_utlenienie", "produkt_K40GL"]


# ── Data loading ─────────────────────────────────────────────────────────────


def load_data() -> pd.DataFrame:
    """Load data directly from verified JSONs."""
    results = []

    for prod_dir in sorted(VERIFIED_DIR.iterdir()):
        if not prod_dir.is_dir():
            continue
        produkt = prod_dir.name.replace("_", " ")
        if produkt not in ("Chegina K7", "Chegina K40GL"):
            continue

        # Find unique batch IDs
        batch_ids = set()
        for f in prod_dir.glob("*.json"):
            name = f.stem
            for suffix in ("_strona1", "_proces", "_koncowa"):
                if name.endswith(suffix):
                    batch_ids.add(name[: -len(suffix)])

        for batch_nr in sorted(batch_ids):
            s1_path = prod_dir / f"{batch_nr}_strona1.json"
            proc_path = prod_dir / f"{batch_nr}_proces.json"
            konc_path = prod_dir / f"{batch_nr}_koncowa.json"

            if not (s1_path.exists() and proc_path.exists() and konc_path.exists()):
                print(f"  SKIP {prod_dir.name}/{batch_nr} — incomplete set")
                continue

            s1 = json.loads(s1_path.read_text())
            proc = json.loads(proc_path.read_text())
            konc = json.loads(konc_path.read_text())

            # pH from utlenienie (last analiza)
            ph_utl, nd20_utl = None, None
            utl = proc.get("etapy", {}).get("utlenienie", {})
            if utl:
                for k in reversed(utl.get("kroki", [])):
                    if k.get("typ") == "analiza":
                        if ph_utl is None:
                            ph_utl = k.get("ph_10proc")
                        if nd20_utl is None:
                            nd20_utl = k.get("nd20")
                        if ph_utl is not None and nd20_utl is not None:
                            break

            # Final pH from koncowa
            ak = konc.get("analiza_koncowa", {}) or {}
            ph_konc = ak.get("ph_10proc")

            # Acid: ONLY from strona1 standaryzowanie (koncowa kontynuacja = duplicates)
            acid_kg = sum(
                s.get("ilosc_kg", 0) or 0
                for s in s1.get("standaryzowanie", [])
                if s.get("kod_dodatku") == "kw_cytrynowy"
            )

            wielkosc = s1.get("wielkosc_szarzy_kg")

            results.append(
                {
                    "batch_id": f"{prod_dir.name}/{batch_nr}",
                    "produkt": produkt,
                    "wielkosc_kg": wielkosc,
                    "ph_utlenienie": ph_utl,
                    "nd20_utlenienie": nd20_utl,
                    "ph_koncowa": ph_konc,
                    "acid_kg": acid_kg,
                }
            )

    df = pd.DataFrame(results)
    df["produkt_K40GL"] = (df["produkt"] == "Chegina K40GL").astype(int)
    df["acid_per_ton"] = df["acid_kg"] / (df["wielkosc_kg"] / 1000)
    df["delta_ph"] = df["ph_utlenienie"] - df["ph_koncowa"]
    df["buffer_cap"] = df["acid_per_ton"] / df["delta_ph"]

    print(f"Loaded {len(df)} batches from verified JSONs")

    # Drop rows without buffer_cap (missing pH or zero delta)
    before = len(df)
    df = df.dropna(subset=["buffer_cap"]).reset_index(drop=True)
    # Also drop inf / negative buffer_cap
    df = df[np.isfinite(df["buffer_cap"]) & (df["buffer_cap"] > 0)].reset_index(
        drop=True
    )
    print(f"Complete cases: {len(df)} (dropped {before - len(df)} with missing data)")

    # Export
    MODEL_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(MODEL_CSV, index=False)
    print(f"Model data saved: {MODEL_CSV}")

    # Summary
    for prod in ["Chegina K40GL", "Chegina K7"]:
        sub = df[df["produkt"] == prod]["buffer_cap"]
        if len(sub) > 1:
            print(
                f"  {prod}: buffer_cap mean={sub.mean():.3f} "
                f"std={sub.std():.3f} cv={sub.std()/sub.mean()*100:.1f}% n={len(sub)}"
            )
        elif len(sub) == 1:
            print(f"  {prod}: buffer_cap={sub.iloc[0]:.3f} n=1")

    return df


# ── VIF ──────────────────────────────────────────────────────────────────────


def check_vif(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    """Compute VIF for given feature list."""
    X = df[features].values
    vif_data = []
    for i, feat in enumerate(features):
        vif_val = variance_inflation_factor(X, i) if len(features) > 1 else 1.0
        vif_data.append({"feature": feat, "VIF": round(vif_val, 2)})
    return pd.DataFrame(vif_data)


# ── Feature selection ────────────────────────────────────────────────────────


def _loo_r2(df: pd.DataFrame, features: list[str]) -> tuple[float, float]:
    """Quick LOO R² and MAE for a feature set. Returns (r2, mae)."""
    X = sm.add_constant(df[features])
    y = df[TARGET].values
    loo = LeaveOneOut()
    preds = np.empty(len(y))
    for train_idx, test_idx in loo.split(X):
        model = sm.OLS(y[train_idx], X.iloc[train_idx]).fit()
        preds[test_idx] = model.predict(X.iloc[test_idx])
    ss_res = np.sum((y - preds) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot
    mae = np.mean(np.abs(y - preds))
    return r2, mae


def select_features(df: pd.DataFrame) -> list[str]:
    """Test all feature combos, print comparison, pick best LOO R² with VIF < 5."""
    print("\n── Feature selection ──")
    rows = []

    for k in range(1, len(ALL_FEATURES) + 1):
        for combo in combinations(ALL_FEATURES, k):
            feats = list(combo)
            vif_df = check_vif(df, feats)
            max_vif = vif_df["VIF"].max()
            r2, mae = _loo_r2(df, feats)
            rows.append(
                {
                    "features": " + ".join(feats),
                    "n_feat": k,
                    "LOO_R2": round(r2, 4),
                    "LOO_MAE": round(mae, 4),
                    "max_VIF": round(max_vif, 2),
                    "VIF_ok": max_vif < 5,
                    "_feats": feats,
                }
            )

    comp = pd.DataFrame(rows).sort_values("LOO_R2", ascending=False)
    print(
        comp[["features", "n_feat", "LOO_R2", "LOO_MAE", "max_VIF", "VIF_ok"]].to_string(
            index=False
        )
    )

    # Pick best LOO R² among VIF-ok combos
    valid = comp[comp["VIF_ok"]]
    if valid.empty:
        print("WARNING: No combo with VIF < 5 — using best overall")
        best = comp.iloc[0]
    else:
        best = valid.iloc[0]

    selected = best["_feats"]
    print(f"\n>>> Selected: {selected}  (LOO R²={best['LOO_R2']}, max VIF={best['max_VIF']})")
    return selected


# ── OLS fit ──────────────────────────────────────────────────────────────────


def fit_ols(
    df: pd.DataFrame, features: list[str]
) -> sm.regression.linear_model.RegressionResultsWrapper:
    """Fit OLS, print summary."""
    X = sm.add_constant(df[features])
    y = df[TARGET]
    model = sm.OLS(y, X).fit()
    print("\n── OLS summary ──")
    print(model.summary())
    return model


# ── LOO-CV ───────────────────────────────────────────────────────────────────


def loo_cv(
    df: pd.DataFrame, features: list[str]
) -> tuple[pd.DataFrame, dict]:
    """LOO cross-validation. Returns predictions df and metrics dict."""
    X = sm.add_constant(df[features])
    y = df[TARGET].values
    loo = LeaveOneOut()
    preds = np.empty(len(y))

    for train_idx, test_idx in loo.split(X):
        model = sm.OLS(y[train_idx], X.iloc[train_idx]).fit()
        preds[test_idx] = model.predict(X.iloc[test_idx])

    residuals = y - preds
    ss_res = np.sum(residuals**2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot
    mae = np.mean(np.abs(residuals))
    rmse = np.sqrt(np.mean(residuals**2))
    mape = np.mean(np.abs(residuals / y)) * 100

    metrics = {"LOO_R2": r2, "MAE": mae, "RMSE": rmse, "MAPE": mape}
    print("\n── LOO-CV ──")
    for k, v in metrics.items():
        print(f"  {k}: {v:.4f}")

    pred_df = df[["batch_id", "produkt", TARGET]].copy()
    pred_df["predicted"] = preds
    pred_df["residual"] = residuals
    pred_df["abs_error"] = np.abs(residuals)
    return pred_df, metrics


# ── Bootstrap CI ─────────────────────────────────────────────────────────────


def bootstrap_ci(
    df: pd.DataFrame, features: list[str], n_boot: int = 2000
) -> pd.DataFrame:
    """Bootstrap confidence intervals for coefficients."""
    X = sm.add_constant(df[features])
    y = df[TARGET].values
    n = len(y)
    coef_names = ["const"] + features
    boot_coefs = np.empty((n_boot, len(coef_names)))

    rng = np.random.default_rng(42)
    for b in range(n_boot):
        idx = rng.choice(n, size=n, replace=True)
        try:
            m = sm.OLS(y[idx], X.iloc[idx]).fit()
            boot_coefs[b] = m.params.values
        except Exception:
            boot_coefs[b] = np.nan

    boot_coefs = boot_coefs[~np.isnan(boot_coefs).any(axis=1)]

    rows = []
    for i, name in enumerate(coef_names):
        lo, hi = np.percentile(boot_coefs[:, i], [2.5, 97.5])
        rows.append(
            {
                "feature": name,
                "boot_mean": np.mean(boot_coefs[:, i]),
                "CI_2.5%": lo,
                "CI_97.5%": hi,
            }
        )

    ci_df = pd.DataFrame(rows)
    print("\n── Bootstrap 95% CI ──")
    print(ci_df.to_string(index=False))
    return ci_df


# ── Diagnostic plots ─────────────────────────────────────────────────────────


def fig_to_base64(fig: plt.Figure) -> str:
    """Convert matplotlib figure to base64 PNG string."""
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return b64


def diagnostics(
    model,
    df: pd.DataFrame,
    features: list[str],
    pred_df: pd.DataFrame,
) -> list[str]:
    """Generate 4 diagnostic plots, return list of base64-encoded PNGs."""
    y = df[TARGET].values
    fitted = model.fittedvalues
    resid = model.resid
    product_colors = df["produkt_K40GL"].map({0: "#2196F3", 1: "#FF9800"}).values

    figs_b64 = []

    # 1. Actual vs Predicted (LOO)
    fig, ax = plt.subplots(figsize=(6, 5))
    for prod, color, label in [
        (0, "#2196F3", "K7"),
        (1, "#FF9800", "K40GL"),
    ]:
        mask = df["produkt_K40GL"] == prod
        ax.scatter(
            pred_df.loc[mask, TARGET],
            pred_df.loc[mask, "predicted"],
            c=color,
            label=label,
            s=50,
            alpha=0.8,
            edgecolors="k",
            linewidth=0.5,
        )
    mn = min(y.min(), pred_df["predicted"].min()) * 0.95
    mx = max(y.max(), pred_df["predicted"].max()) * 1.05
    ax.plot([mn, mx], [mn, mx], "k--", alpha=0.5)
    ax.set_xlabel("Actual buffer_cap")
    ax.set_ylabel("LOO Predicted buffer_cap")
    ax.set_title("Actual vs LOO Predicted")
    ax.legend()
    fig.tight_layout()
    figs_b64.append(fig_to_base64(fig))

    # 2. Residuals vs Fitted
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.scatter(fitted, resid, c=product_colors, s=50, alpha=0.8, edgecolors="k", linewidth=0.5)
    ax.axhline(0, color="k", linestyle="--", alpha=0.5)
    ax.set_xlabel("Fitted values")
    ax.set_ylabel("Residuals")
    ax.set_title("Residuals vs Fitted")
    fig.tight_layout()
    figs_b64.append(fig_to_base64(fig))

    # 3. Q-Q plot
    fig, ax = plt.subplots(figsize=(6, 5))
    sm.qqplot(resid, line="45", ax=ax, markersize=5)
    ax.set_title("Q-Q Plot of Residuals")
    fig.tight_layout()
    figs_b64.append(fig_to_base64(fig))

    # 4. Cook's distance
    influence = model.get_influence()
    cooks_d = influence.cooks_distance[0]
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.stem(range(len(cooks_d)), cooks_d, markerfmt=",", basefmt="k-")
    ax.axhline(4 / len(y), color="r", linestyle="--", alpha=0.7, label=f"4/n = {4/len(y):.3f}")
    ax.set_xlabel("Observation")
    ax.set_ylabel("Cook's distance")
    ax.set_title("Cook's Distance")
    ax.legend()
    fig.tight_layout()
    figs_b64.append(fig_to_base64(fig))

    return figs_b64


# ── HTML report ──────────────────────────────────────────────────────────────


def generate_report(
    df: pd.DataFrame,
    model,
    features: list[str],
    vif_df: pd.DataFrame,
    pred_df: pd.DataFrame,
    loo_metrics: dict,
    boot_ci_df: pd.DataFrame,
    diag_figs: list[str],
) -> None:
    """Generate HTML report and save to OUT_HTML."""
    # Build formula string
    coefs = model.params
    formula_parts = [f"{coefs['const']:.4f}"]
    for feat in features:
        sign = "+" if coefs[feat] >= 0 else "-"
        formula_parts.append(f" {sign} {abs(coefs[feat]):.4f} * {feat}")
    formula_str = "".join(formula_parts)

    # Example calculation (first K7 row)
    ex = df[df["produkt_K40GL"] == 0].iloc[0]
    ex_row = pd.DataFrame([ex[features].to_dict()])
    ex_row.insert(0, "const", 1.0)
    bc_ex = model.predict(ex_row).iloc[0]
    dose_ex = bc_ex * ex["delta_ph"] * (ex["wielkosc_kg"] / 1000)

    # Feature ranges
    ranges_html = ""
    for feat in features:
        lo, hi = df[feat].min(), df[feat].max()
        ranges_html += f"<tr><td>{feat}</td><td>{lo:.1f}</td><td>{hi:.1f}</td></tr>\n"

    # Coefficient table
    coef_rows = ""
    for _, row in boot_ci_df.iterrows():
        ols_val = coefs.get(row["feature"], 0)
        pval = model.pvalues.get(row["feature"], np.nan)
        coef_rows += (
            f"<tr><td>{row['feature']}</td>"
            f"<td>{ols_val:.4f}</td>"
            f"<td>{pval:.4f}</td>"
            f"<td>[{row['CI_2.5%']:.4f}, {row['CI_97.5%']:.4f}]</td></tr>\n"
        )

    # VIF table
    vif_rows = ""
    for _, row in vif_df.iterrows():
        vif_rows += f"<tr><td>{row['feature']}</td><td>{row['VIF']:.2f}</td></tr>\n"

    # LOO predictions table
    pred_rows = ""
    for _, row in pred_df.sort_values("abs_error", ascending=False).iterrows():
        pred_rows += (
            f"<tr><td>{row['batch_id']}</td>"
            f"<td>{row['produkt']}</td>"
            f"<td>{row[TARGET]:.3f}</td>"
            f"<td>{row['predicted']:.3f}</td>"
            f"<td>{row['residual']:+.3f}</td></tr>\n"
        )

    # Per-product stats
    product_stats = ""
    for prod in ["Chegina K7", "Chegina K40GL"]:
        sub = df[df["produkt"] == prod]["buffer_cap"]
        if len(sub) > 1:
            product_stats += (
                f"<tr><td>{prod}</td><td>{len(sub)}</td>"
                f"<td>{sub.mean():.3f}</td><td>{sub.std():.3f}</td>"
                f"<td>{sub.std()/sub.mean()*100:.1f}%</td></tr>\n"
            )

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<title>Model buffer capacity - kwas cytrynowy</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 1000px; margin: 30px auto; padding: 0 20px; color: #333; }}
  h1 {{ color: #1565C0; border-bottom: 2px solid #1565C0; padding-bottom: 8px; }}
  h2 {{ color: #2E7D32; margin-top: 30px; }}
  table {{ border-collapse: collapse; margin: 12px 0; width: 100%; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: right; }}
  th {{ background: #f5f5f5; text-align: center; }}
  td:first-child {{ text-align: left; }}
  .metric-box {{ display: inline-block; background: #e3f2fd; border-radius: 8px; padding: 12px 20px; margin: 6px; text-align: center; }}
  .metric-box .val {{ font-size: 1.5em; font-weight: bold; color: #1565C0; }}
  .metric-box .lbl {{ font-size: 0.85em; color: #555; }}
  .formula-box {{ background: #fff3e0; border-left: 4px solid #FF9800; padding: 15px; margin: 15px 0; font-family: monospace; font-size: 1.1em; }}
  .operator-box {{ background: #e8f5e9; border-left: 4px solid #4CAF50; padding: 15px; margin: 15px 0; }}
  .note {{ background: #fce4ec; border-left: 4px solid #e91e63; padding: 12px; margin: 12px 0; }}
  img {{ max-width: 100%; margin: 8px 0; }}
  .plot-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
</style>
</head>
<body>

<h1>Model buffer capacity &mdash; dawkowanie kwasu cytrynowego</h1>
<p>Raport wygenerowany automatycznie z danych zweryfikowanych JSON.</p>

<h2>1. Metryki modelu</h2>
<div>
  <div class="metric-box"><div class="val">{model.rsquared:.3f}</div><div class="lbl">R&sup2;</div></div>
  <div class="metric-box"><div class="val">{model.rsquared_adj:.3f}</div><div class="lbl">Adj R&sup2;</div></div>
  <div class="metric-box"><div class="val">{loo_metrics['LOO_R2']:.3f}</div><div class="lbl">LOO R&sup2;</div></div>
  <div class="metric-box"><div class="val">{loo_metrics['MAE']:.4f}</div><div class="lbl">LOO MAE</div></div>
  <div class="metric-box"><div class="val">{loo_metrics['RMSE']:.4f}</div><div class="lbl">LOO RMSE</div></div>
  <div class="metric-box"><div class="val">{loo_metrics['MAPE']:.1f}%</div><div class="lbl">LOO MAPE</div></div>
</div>

<h2>2. Formula modelu</h2>
<div class="formula-box">
  buffer_cap = {formula_str}
</div>

<h2>3. Statystyki per produkt</h2>
<table>
  <tr><th>Produkt</th><th>n</th><th>mean</th><th>std</th><th>CV</th></tr>
  {product_stats}
</table>

<h2>4. Wzor operatorski</h2>
<div class="operator-box">
  <p><strong>Dawka kwasu cytrynowego [kg]:</strong></p>
  <p style="font-family:monospace; font-size:1.1em;">
    dawka_kwasu_kg = buffer_cap &times; (pH_utlenienie &minus; pH_docelowe) &times; (wielkosc_kg / 1000)
  </p>
  <p>gdzie <code>buffer_cap</code> obliczamy z modelu powyzej.</p>
  <hr>
  <p><strong>Przyklad (szarza {ex['batch_id']}):</strong></p>
  <ul>
    <li>wielkosc_kg = {ex['wielkosc_kg']:.0f}</li>
    <li>ph_utlenienie = {ex['ph_utlenienie']:.2f}</li>
    <li>ph_docelowe (koncowa) = {ex['ph_koncowa']:.2f}</li>
    <li>buffer_cap (model) = {bc_ex:.3f}</li>
    <li><strong>dawka = {bc_ex:.3f} &times; ({ex['ph_utlenienie']:.2f} &minus; {ex['ph_koncowa']:.2f}) &times; {ex['wielkosc_kg']/1000:.1f} = {dose_ex:.1f} kg</strong></li>
    <li>Rzeczywista dawka: {ex['acid_kg']:.1f} kg</li>
  </ul>
</div>

<div class="note">
  <strong>Uwaga:</strong> K40GL ma bardzo stabilna buffer capacity (~1.71, CV ~4%), wiec prosty srednia moze
  wystarczyc. K7 jest bardziej zmienny (CV ~18%) i korzysta z regresji uwzgledniajacej wielkosc szarzy i pH utlenienia.
</div>

<h2>5. Wspolczynniki i VIF</h2>
<table>
  <tr><th>Feature</th><th>Coef (OLS)</th><th>p-value</th><th>Bootstrap 95% CI</th></tr>
  {coef_rows}
</table>

<h3>VIF (Variance Inflation Factor)</h3>
<table>
  <tr><th>Feature</th><th>VIF</th></tr>
  {vif_rows}
</table>

<h2>6. Zakresy zmiennych (validity)</h2>
<table>
  <tr><th>Feature</th><th>Min</th><th>Max</th></tr>
  {ranges_html}
</table>

<h2>7. LOO Predictions</h2>
<table>
  <tr><th>Batch</th><th>Produkt</th><th>Actual</th><th>Predicted</th><th>Residual</th></tr>
  {pred_rows}
</table>

<h2>8. Diagnostyka</h2>
<div class="plot-grid">
  <div><img src="data:image/png;base64,{diag_figs[0]}" alt="Actual vs Predicted"></div>
  <div><img src="data:image/png;base64,{diag_figs[1]}" alt="Residuals vs Fitted"></div>
  <div><img src="data:image/png;base64,{diag_figs[2]}" alt="Q-Q Plot"></div>
  <div><img src="data:image/png;base64,{diag_figs[3]}" alt="Cook's Distance"></div>
</div>

</body>
</html>"""

    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"\nHTML report saved: {OUT_HTML}")


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    print("=" * 60)
    print("  Buffer Capacity Model — Citric Acid Dosage")
    print("=" * 60)

    # 1. Load data
    df = load_data()
    if len(df) < 5:
        print(f"ERROR: Only {len(df)} complete rows — too few for modelling.")
        return

    # 2. Select features
    features = select_features(df)

    # 3. Fit OLS
    model = fit_ols(df, features)

    # 4. LOO-CV
    pred_df, loo_metrics = loo_cv(df, features)

    # 5. VIF
    vif_df = check_vif(df, features)

    # 6. Bootstrap CIs
    boot_ci_df = bootstrap_ci(df, features)

    # 7. Diagnostics + report
    diag_figs = diagnostics(model, df, features, pred_df)
    generate_report(df, model, features, vif_df, pred_df, loo_metrics, boot_ci_df, diag_figs)

    # 8. Summary
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  Features:   {features}")
    print(f"  R²:         {model.rsquared:.4f}")
    print(f"  Adj R²:     {model.rsquared_adj:.4f}")
    print(f"  LOO R²:     {loo_metrics['LOO_R2']:.4f}")
    print(f"  LOO MAE:    {loo_metrics['MAE']:.4f}")
    print(f"  LOO RMSE:   {loo_metrics['RMSE']:.4f}")
    print(f"  LOO MAPE:   {loo_metrics['MAPE']:.1f}%")
    print(f"  Report:     {OUT_HTML}")
    print(f"  Data CSV:   {MODEL_CSV}")


if __name__ == "__main__":
    main()
