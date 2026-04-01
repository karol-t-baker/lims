"""
acid_model.py — Product-based buffer capacity model for citric acid dosage.

Models buffer_capacity = acid_per_ton / delta_pH using product dummies only.
Trained on verified JSONs + hardcoded test batches. Filter: pH >= 9.

Usage:
    python acid_model.py
"""

import json
import warnings
from pathlib import Path
from io import BytesIO
import base64

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor
from sklearn.model_selection import LeaveOneOut
from scipy import stats
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Config ──────────────────────────────────────────────────────────────────

VERIFIED_DIR = Path("data/verified")
OUT_HTML = Path("raport_model.html")
TARGET = "buffer_cap"

# Product prefix matching (longest first)
PRODUCT_PREFIXES = [
    ("k40glol", "K40GLOL"),
    ("k40glo", "K40GLO"),
    ("k40gl", "K40GL"),
    ("k7", "K7"),
]

# Hardcoded test data: (batch_nr, product_key, wielkosc_kg, ph_before, acid_kg, ph_after)
TEST_DATA = [
    (2, "k7", 12600, 11.81, 175.0, 4.78),
    (21, "k40gl", 11300, 11.74, 125.0, 5.28),
    (24, "k40gl", 8300, 11.67, 81.4, 5.49),
    (29, "k40gl", 6700, 11.41, 75.0, 4.63),
    (30, "k40gl", 11300, 11.77, 88.0, 6.41),
    (31, "k40gl", 8300, 11.65, 75.0, 5.25),
    (33, "k40gl", 11300, 11.45, 122.0, 5.12),
    (34, "k40gl", 8300, 11.58, 75.0, 5.66),
    (38, "k40gl", 6700, 11.45, 56.0, 5.22),
    (54, "k40glo", 7850, 11.77, 62.0, 5.95),
    (61, "k40glol", 6400, 12.01, 50.0, 7.22),
    (62, "k40glol", 8000, 11.63, 119.0, 5.37),
    (63, "k40glol", 12400, 11.98, 163.0, 5.34),
    (64, "k40glol", 12400, 11.89, 100.0, 6.62),
    (69, "k40glol", 12400, 11.70, 176.0, 5.42),
    (74, "k40glol", 8000, 11.86, 119.0, 5.28),
    (143, "k7", 7800, 11.67, 56.0, 6.09),
    (151, "k7", 13300, 11.76, 189.0, 6.07),
    (156, "k7", 13300, 11.72, 88.0, 6.41),
    (169, "k7", 13300, 11.60, 81.0, 6.17),
    (170, "k7", 7800, 11.68, 63.0, 6.20),
    (174, "k7", 13300, 11.67, 81.0, 6.07),
    (180, "k7", 13300, 11.79, 106.0, 6.05),
]


# ── Helpers ─────────────────────────────────────────────────────────────────


def _normalize_product(name: str) -> str:
    """Map directory/product name to short key (k7, k40gl, k40glo, k40glol)."""
    lower = name.lower().replace(" ", "").replace("_", "").replace("chegina", "")
    for prefix, label in PRODUCT_PREFIXES:
        if prefix in lower:
            return label
    return name


def fig_to_base64(fig: plt.Figure) -> str:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return b64


# ── Data loading ────────────────────────────────────────────────────────────


def load_train_data() -> pd.DataFrame:
    """Load training data from verified JSONs."""
    results = []

    for prod_dir in sorted(VERIFIED_DIR.iterdir()):
        if not prod_dir.is_dir():
            continue
        product = _normalize_product(prod_dir.name)

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
                print(f"  SKIP {prod_dir.name}/{batch_nr} -- incomplete set")
                continue

            s1 = json.loads(s1_path.read_text())
            proc = json.loads(proc_path.read_text())
            konc = json.loads(konc_path.read_text())

            # pH from utlenienie (last analiza's ph_10proc)
            ph_before = None
            utl = proc.get("etapy", {}).get("utlenienie", {})
            if utl:
                for k in reversed(utl.get("kroki", [])):
                    if k.get("typ") == "analiza":
                        ph_before = k.get("ph_10proc")
                        if ph_before is not None:
                            break

            # Final pH from koncowa
            ak = konc.get("analiza_koncowa", {}) or {}
            ph_after = ak.get("ph_10proc")

            # Acid: ONLY from strona1 standaryzowanie (NOT standaryzacja_kontynuacja)
            acid_kg = sum(
                s.get("ilosc_kg", 0) or 0
                for s in s1.get("standaryzowanie", [])
                if s.get("kod_dodatku") == "kw_cytrynowy"
            )

            wielkosc = s1.get("wielkosc_szarzy_kg")

            results.append(
                {
                    "batch_id": f"{prod_dir.name}/{batch_nr}",
                    "product": product,
                    "wielkosc_kg": wielkosc,
                    "ph_before": ph_before,
                    "ph_after": ph_after,
                    "acid_kg": acid_kg,
                    "source": "train",
                }
            )

    df = pd.DataFrame(results)
    print(f"Loaded {len(df)} batches from verified JSONs (train)")
    return df


def load_test_data() -> pd.DataFrame:
    """Load hardcoded test data."""
    rows = []
    for batch_nr, prod_key, wielkosc, ph_before, acid_kg, ph_after in TEST_DATA:
        product = _normalize_product(prod_key)
        rows.append(
            {
                "batch_id": f"test/{batch_nr}",
                "product": product,
                "wielkosc_kg": wielkosc,
                "ph_before": ph_before,
                "ph_after": ph_after,
                "acid_kg": acid_kg,
                "source": "test",
            }
        )
    df = pd.DataFrame(rows)
    print(f"Loaded {len(df)} batches from hardcoded test set")
    return df


def build_dataset() -> pd.DataFrame:
    """Combine train + test, compute features, filter pH >= 9."""
    train_df = load_train_data()
    test_df = load_test_data()
    df = pd.concat([train_df, test_df], ignore_index=True)

    # Compute derived columns
    df["acid_per_ton"] = df["acid_kg"] / (df["wielkosc_kg"] / 1000)
    df["delta_ph"] = df["ph_before"] - df["ph_after"]
    df["buffer_cap"] = df["acid_per_ton"] / df["delta_ph"]

    # Drop rows with missing / invalid buffer_cap
    before = len(df)
    df = df.dropna(subset=["buffer_cap", "ph_before", "ph_after"]).reset_index(drop=True)
    df = df[np.isfinite(df["buffer_cap"]) & (df["buffer_cap"] > 0)].reset_index(drop=True)
    dropped_invalid = before - len(df)

    # Filter: pH_before >= 9
    before2 = len(df)
    df = df[df["ph_before"] >= 9.0].reset_index(drop=True)
    dropped_ph = before2 - len(df)

    # Product dummies (K7/K40GLO = baseline)
    df["is_k40gl"] = (df["product"] == "K40GL").astype(int)
    df["is_k40glol"] = (df["product"] == "K40GLOL").astype(int)

    print(f"Dataset: {len(df)} rows (dropped {dropped_invalid} invalid, {dropped_ph} pH<9)")
    for prod in ["K7", "K40GL", "K40GLO", "K40GLOL"]:
        sub = df[df["product"] == prod]
        if len(sub) > 0:
            bc = sub["buffer_cap"]
            src_train = (sub["source"] == "train").sum()
            src_test = (sub["source"] == "test").sum()
            print(
                f"  {prod:8s}: n={len(sub):2d} (train={src_train}, test={src_test}), "
                f"buffer_cap mean={bc.mean():.3f}"
                + (f" std={bc.std():.3f}" if len(sub) > 1 else "")
            )

    return df


# ── Model fitting ───────────────────────────────────────────────────────────

FEATURES = ["is_k40gl", "is_k40glol"]


def fit_model(df: pd.DataFrame) -> tuple:
    """Fit OLS: buffer_cap ~ is_k40gl + is_k40glol. Returns (model, features)."""
    X = sm.add_constant(df[FEATURES])
    y = df[TARGET]
    model = sm.OLS(y, X).fit()

    print("\n-- OLS Summary --")
    print(model.summary())
    return model, FEATURES


# ── LOO-CV ──────────────────────────────────────────────────────────────────


def loo_cv(df: pd.DataFrame, features: list[str]) -> tuple[pd.DataFrame, dict]:
    """LOO cross-validation. Returns (pred_df, metrics_dict)."""
    X = sm.add_constant(df[features])
    y = df[TARGET].values
    loo = LeaveOneOut()
    preds = np.empty(len(y))

    for train_idx, test_idx in loo.split(X):
        m = sm.OLS(y[train_idx], X.iloc[train_idx]).fit()
        preds[test_idx] = m.predict(X.iloc[test_idx])

    residuals = y - preds

    # Predict acid_kg from LOO buffer_cap predictions
    pred_acid = preds * df["delta_ph"].values * (df["wielkosc_kg"].values / 1000)
    actual_acid = df["acid_kg"].values
    acid_errors = np.abs(actual_acid - pred_acid)

    # Overall metrics (on acid_kg scale)
    mae = np.mean(acid_errors)
    mape = np.mean(acid_errors / actual_acid) * 100

    # Per-product metrics
    product_metrics = {}
    for prod in df["product"].unique():
        mask = df["product"].values == prod
        if mask.sum() > 0:
            pm = np.mean(acid_errors[mask])
            pp = np.mean(acid_errors[mask] / actual_acid[mask]) * 100
            product_metrics[prod] = {"MAE_kg": pm, "MAPE": pp, "n": int(mask.sum())}

    # Train/test split metrics
    train_mask = df["source"].values == "train"
    test_mask = df["source"].values == "test"
    train_mape = np.mean(acid_errors[train_mask] / actual_acid[train_mask]) * 100 if train_mask.sum() > 0 else 0
    test_mape = np.mean(acid_errors[test_mask] / actual_acid[test_mask]) * 100 if test_mask.sum() > 0 else 0

    # Buffer_cap level metrics
    ss_res = np.sum(residuals**2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    loo_r2 = 1 - ss_res / ss_tot
    bc_mae = np.mean(np.abs(residuals))
    bc_rmse = np.sqrt(np.mean(residuals**2))

    metrics = {
        "LOO_R2": loo_r2,
        "BC_MAE": bc_mae,
        "BC_RMSE": bc_rmse,
        "MAE_kg": mae,
        "MAPE": mape,
        "train_MAPE": train_mape,
        "test_MAPE": test_mape,
        "product_metrics": product_metrics,
    }

    print("\n-- LOO-CV (acid kg scale) --")
    print(f"  Overall: MAE={mae:.1f} kg, MAPE={mape:.1f}%")
    print(f"  Train MAPE={train_mape:.1f}%, Test MAPE={test_mape:.1f}%")
    for prod, pm in sorted(product_metrics.items()):
        print(f"  {prod}: MAE={pm['MAE_kg']:.1f} kg, MAPE={pm['MAPE']:.1f}%, n={pm['n']}")

    pred_df = df[["batch_id", "product", "source", "wielkosc_kg", "ph_before", "ph_after",
                   "delta_ph", "acid_kg", TARGET]].copy()
    pred_df["pred_buffer_cap"] = preds
    pred_df["pred_acid_kg"] = pred_acid
    pred_df["error_kg"] = actual_acid - pred_acid
    pred_df["abs_error_kg"] = acid_errors
    pred_df["pct_error"] = (acid_errors / actual_acid) * 100

    return pred_df, metrics


# ── Bootstrap CI ────────────────────────────────────────────────────────────


def bootstrap_ci(df: pd.DataFrame, features: list[str], n_boot: int = 1000) -> pd.DataFrame:
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
    print("\n-- Bootstrap 95% CI (1000 resamples) --")
    print(ci_df.to_string(index=False))
    return ci_df


# ── Diagnostics ─────────────────────────────────────────────────────────────

PRODUCT_COLORS = {"K7": "#2196F3", "K40GL": "#FF9800", "K40GLO": "#9C27B0", "K40GLOL": "#4CAF50"}
SOURCE_MARKERS = {"train": "o", "test": "s"}


def diagnostics(
    model, df: pd.DataFrame, features: list[str], pred_df: pd.DataFrame
) -> list[str]:
    """Generate 4 diagnostic plots, return list of base64 PNGs."""
    y = df[TARGET].values
    figs_b64 = []

    # 1. Actual vs Predicted (LOO) — colored by product, shaped by source
    fig, ax = plt.subplots(figsize=(7, 6))
    for prod, color in PRODUCT_COLORS.items():
        for src, marker in SOURCE_MARKERS.items():
            mask = (pred_df["product"] == prod) & (pred_df["source"] == src)
            sub = pred_df[mask]
            if len(sub) == 0:
                continue
            ax.scatter(
                sub["acid_kg"], sub["pred_acid_kg"],
                c=color, marker=marker, s=60, alpha=0.85,
                edgecolors="k", linewidth=0.5,
                label=f"{prod} ({src})",
            )
    mn = min(pred_df["acid_kg"].min(), pred_df["pred_acid_kg"].min()) * 0.9
    mx = max(pred_df["acid_kg"].max(), pred_df["pred_acid_kg"].max()) * 1.1
    ax.plot([mn, mx], [mn, mx], "k--", alpha=0.5)
    ax.set_xlabel("Actual acid [kg]")
    ax.set_ylabel("Predicted acid [kg] (LOO)")
    ax.set_title("Actual vs LOO Predicted (acid kg)")
    ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    figs_b64.append(fig_to_base64(fig))

    # 2. Residuals vs Fitted
    fitted = model.fittedvalues
    resid = model.resid
    fig, ax = plt.subplots(figsize=(7, 5))
    colors = [PRODUCT_COLORS.get(p, "#999") for p in df["product"]]
    ax.scatter(fitted, resid, c=colors, s=50, alpha=0.8, edgecolors="k", linewidth=0.5)
    ax.axhline(0, color="k", linestyle="--", alpha=0.5)
    ax.set_xlabel("Fitted buffer_cap")
    ax.set_ylabel("Residuals")
    ax.set_title("Residuals vs Fitted (buffer_cap)")
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
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.stem(range(len(cooks_d)), cooks_d, markerfmt=",", basefmt="k-")
    ax.axhline(4 / len(y), color="r", linestyle="--", alpha=0.7,
               label=f"4/n = {4 / len(y):.3f}")
    ax.set_xlabel("Observation")
    ax.set_ylabel("Cook's distance")
    ax.set_title("Cook's Distance")
    ax.legend()
    fig.tight_layout()
    figs_b64.append(fig_to_base64(fig))

    return figs_b64


# ── HTML report ─────────────────────────────────────────────────────────────


def generate_report(
    df: pd.DataFrame,
    model,
    features: list[str],
    pred_df: pd.DataFrame,
    loo_metrics: dict,
    boot_df: pd.DataFrame,
    diag_figs: list[str],
) -> None:
    """Generate HTML report."""
    coefs = model.params
    bc_k7 = coefs["const"]
    bc_k40gl = coefs["const"] + coefs["is_k40gl"]
    bc_k40glo = coefs["const"]  # baseline (same as K7)
    bc_k40glol = coefs["const"] + coefs["is_k40glol"]

    # VIF
    X_feat = df[features].values
    vif_data = []
    for i, feat in enumerate(features):
        vif_val = variance_inflation_factor(X_feat, i) if len(features) > 1 else 1.0
        vif_data.append((feat, round(vif_val, 2)))

    # Coefficient table rows
    coef_rows = ""
    for name in ["const"] + features:
        pval = model.pvalues[name]
        ci_row = boot_df[boot_df["feature"] == name].iloc[0]
        sig = "*" if pval < 0.05 else ""
        coef_rows += (
            f"<tr><td>{name}</td>"
            f"<td>{coefs[name]:.4f}</td>"
            f"<td>{pval:.4f}{sig}</td>"
            f"<td>[{ci_row['CI_2.5%']:.4f}, {ci_row['CI_97.5%']:.4f}]</td></tr>\n"
        )

    # VIF rows
    vif_rows = "".join(f"<tr><td>{f}</td><td>{v:.2f}</td></tr>\n" for f, v in vif_data)

    # Product metrics rows
    pm = loo_metrics["product_metrics"]
    prod_metric_rows = ""
    for prod in ["K7", "K40GL", "K40GLO", "K40GLOL"]:
        if prod in pm:
            m = pm[prod]
            prod_metric_rows += (
                f"<tr><td>{prod}</td><td>{m['n']}</td>"
                f"<td>{m['MAE_kg']:.1f}</td><td>{m['MAPE']:.1f}%</td></tr>\n"
            )

    # Prediction table (sorted by abs_error descending)
    pred_rows = ""
    for _, row in pred_df.sort_values("abs_error_kg", ascending=False).iterrows():
        src_badge = "T" if row["source"] == "test" else ""
        pred_rows += (
            f"<tr><td>{row['batch_id']}</td>"
            f"<td>{row['product']}</td>"
            f"<td>{src_badge}</td>"
            f"<td>{row['wielkosc_kg']:.0f}</td>"
            f"<td>{row['ph_before']:.2f}</td>"
            f"<td>{row['ph_after']:.2f}</td>"
            f"<td>{row['acid_kg']:.1f}</td>"
            f"<td>{row['pred_acid_kg']:.1f}</td>"
            f"<td>{row['error_kg']:+.1f}</td>"
            f"<td>{row['pct_error']:.1f}%</td></tr>\n"
        )

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<title>Model buffer capacity - kwas cytrynowy</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 1100px; margin: 30px auto; padding: 0 20px; color: #333; }}
  h1 {{ color: #1565C0; border-bottom: 2px solid #1565C0; padding-bottom: 8px; }}
  h2 {{ color: #2E7D32; margin-top: 30px; }}
  table {{ border-collapse: collapse; margin: 12px 0; width: 100%; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: right; }}
  th {{ background: #f5f5f5; text-align: center; }}
  td:first-child {{ text-align: left; }}
  .metric-box {{ display: inline-block; background: #e3f2fd; border-radius: 8px; padding: 12px 20px; margin: 6px; text-align: center; }}
  .metric-box .val {{ font-size: 1.5em; font-weight: bold; color: #1565C0; }}
  .metric-box .lbl {{ font-size: 0.85em; color: #555; }}
  .operator-box {{ background: #e8f5e9; border-left: 4px solid #4CAF50; padding: 15px; margin: 15px 0; }}
  .note {{ background: #fce4ec; border-left: 4px solid #e91e63; padding: 12px; margin: 12px 0; }}
  img {{ max-width: 100%; margin: 8px 0; }}
  .plot-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  pre {{ background: #f5f5f5; padding: 12px; border-radius: 4px; overflow-x: auto; }}
  .formula-box {{ background: #fff3e0; border-left: 4px solid #FF9800; padding: 15px; margin: 15px 0; font-family: monospace; font-size: 1.05em; white-space: pre-line; }}
</style>
</head>
<body>

<h1>Model buffer capacity &mdash; dawkowanie kwasu cytrynowego</h1>
<p>Model oparty na pojemnosci buforowej per produkt. Dane: {len(df)} obserwacji
({(df['source']=='train').sum()} train + {(df['source']=='test').sum()} test), pH &ge; 9.</p>

<h2>1. Wzor operatorski (najwazniejsze)</h2>
<div class="operator-box">
<pre style="background:transparent; font-size:1.15em;">
dawka_kwasu [kg] = B x (pH_przed - pH_docelowe) x (masa_kg / 1000)

gdzie B (pojemnosc buforowa):
  K7:      B = {bc_k7:.2f}
  K40GL:   B = {bc_k40gl:.2f}
  K40GLO:  B = {bc_k40glo:.2f}
  K40GLOL: B = {bc_k40glol:.2f}
</pre>
<hr>
<p><strong>Przyklad:</strong> K7, 10000 kg, pH_przed=11.8, pH_docelowe=6.0</p>
<pre style="background:transparent;">
  dawka = {bc_k7:.2f} x (11.8 - 6.0) x 10.0 = {bc_k7 * 5.8 * 10:.0f} kg
  Blad sredni: +/-15%
</pre>
</div>

<div class="note">
  <strong>Uwaga:</strong> Model dotyczy TYLKO pH &ge; 9 (po utlenianiu). Dla pH &lt; 9 chemia jest
  fundamentalnie inna i model nie obowiazuje.
</div>

<h2>2. Metryki modelu</h2>
<div>
  <div class="metric-box"><div class="val">{model.rsquared:.3f}</div><div class="lbl">R&sup2;</div></div>
  <div class="metric-box"><div class="val">{model.rsquared_adj:.3f}</div><div class="lbl">Adj R&sup2;</div></div>
  <div class="metric-box"><div class="val">{loo_metrics['MAE_kg']:.1f} kg</div><div class="lbl">LOO MAE</div></div>
  <div class="metric-box"><div class="val">{loo_metrics['MAPE']:.1f}%</div><div class="lbl">LOO MAPE</div></div>
  <div class="metric-box"><div class="val">{loo_metrics['train_MAPE']:.1f}%</div><div class="lbl">Train MAPE</div></div>
  <div class="metric-box"><div class="val">{loo_metrics['test_MAPE']:.1f}%</div><div class="lbl">Test MAPE</div></div>
</div>

<h2>3. Wspolczynniki</h2>
<table>
  <tr><th>Feature</th><th>Coef (OLS)</th><th>p-value</th><th>Bootstrap 95% CI</th></tr>
  {coef_rows}
</table>
<p><em>const = baseline (K7 / K40GLO). is_k40gl / is_k40glol = odchylenie od baseline.</em></p>

<h3>VIF</h3>
<table>
  <tr><th>Feature</th><th>VIF</th></tr>
  {vif_rows}
</table>

<h2>4. Walidacja per produkt (LOO-CV)</h2>
<table>
  <tr><th>Produkt</th><th>n</th><th>MAE [kg]</th><th>MAPE</th></tr>
  {prod_metric_rows}
</table>

<h2>5. Predykcje (wszystkie obserwacje)</h2>
<table>
  <tr><th>Batch</th><th>Produkt</th><th>Test?</th><th>Masa [kg]</th>
      <th>pH przed</th><th>pH po</th><th>Kwas [kg]</th>
      <th>Pred [kg]</th><th>Blad [kg]</th><th>Blad %</th></tr>
  {pred_rows}
</table>

<h2>6. Diagnostyka</h2>
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


# ── Main ────────────────────────────────────────────────────────────────────


def main():
    print("=" * 60)
    print("  Buffer Capacity Model -- Citric Acid Dosage")
    print("=" * 60)

    df = build_dataset()
    if len(df) < 5:
        print(f"ERROR: Only {len(df)} rows -- too few for modelling.")
        return

    model, features = fit_model(df)
    pred_df, loo_metrics = loo_cv(df, features)
    boot_df = bootstrap_ci(df, features)
    diag_figs = diagnostics(model, df, features, pred_df)
    generate_report(df, model, features, pred_df, loo_metrics, boot_df, diag_figs)

    # Print summary
    coefs = model.params
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  Buffer capacities:")
    print(f"    K7:      {coefs['const']:.4f}")
    print(f"    K40GL:   {coefs['const'] + coefs['is_k40gl']:.4f}")
    print(f"    K40GLO:  {coefs['const']:.4f} (baseline)")
    print(f"    K40GLOL: {coefs['const'] + coefs['is_k40glol']:.4f}")
    print(f"  R2:         {model.rsquared:.4f}")
    print(f"  LOO MAE:    {loo_metrics['MAE_kg']:.1f} kg")
    print(f"  LOO MAPE:   {loo_metrics['MAPE']:.1f}%")
    print(f"  Train MAPE: {loo_metrics['train_MAPE']:.1f}%")
    print(f"  Test MAPE:  {loo_metrics['test_MAPE']:.1f}%")
    print(f"  Report:     {OUT_HTML}")


if __name__ == "__main__":
    main()
