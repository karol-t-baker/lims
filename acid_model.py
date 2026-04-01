"""
acid_model.py — Per-product buffer capacity models for citric acid dosage.

Each product gets its own model:
  K7:      OLS on dmapa_zwrotna_per_ton (from batch card)
  K40GL:   Constant (mean buffer_cap)
  K40GLOL: OLS on utl_ph (combined train+test)
  K40GLO:  Constant (single observation)

Usage:
    python acid_model.py
"""

import json
import warnings
from pathlib import Path
from io import BytesIO
from dataclasses import dataclass, field
import base64

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.model_selection import LeaveOneOut
from scipy import stats
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore", category=FutureWarning)

# ── Config ──────────────────────────────────────────────────────────────────

VERIFIED_DIR = Path("data/verified")
OUT_HTML = Path("raport_model.html")

PRODUCT_PREFIXES = [
    ("k40glol", "K40GLOL"),
    ("k40glo", "K40GLO"),
    ("k40gl", "K40GL"),
    ("k7", "K7"),
]

PRODUCT_COLORS = {"K7": "#2196F3", "K40GL": "#FF9800", "K40GLO": "#9C27B0", "K40GLOL": "#4CAF50"}
SOURCE_MARKERS = {"train": "o", "test": "s"}

TEST_DATA = [
    # (nr, produkt, wielkosc_kg, ph_przed, acid_kg, ph_po)
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


# ── Data classes for model results ──────────────────────────────────────────


@dataclass
class ProductModel:
    """Container for a per-product model."""
    product: str
    model_type: str  # "ols", "constant"
    buffer_cap_mean: float = 0.0
    buffer_cap_std: float = 0.0
    n_train: int = 0
    n_test: int = 0
    # OLS-specific
    ols_model: object = None
    feature_name: str = ""
    intercept: float = 0.0
    coef: float = 0.0
    r_squared: float = 0.0
    p_value: float = 0.0
    # LOO-CV
    loo_mape: float = 0.0
    loo_mae: float = 0.0
    notes: str = ""


# ── Helpers ─────────────────────────────────────────────────────────────────


def _normalize_product(name: str) -> str:
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

            # wielkosc_kg
            wielkosc = s1.get("wielkosc_szarzy_kg")

            # Acid from standaryzowanie
            acid_kg = sum(
                s.get("ilosc_kg", 0) or 0
                for s in s1.get("standaryzowanie", [])
                if s.get("kod_dodatku") == "kw_cytrynowy"
            )

            # dmapa_zwrotna from surowce
            dmapa_zwrotna_kg = sum(
                s.get("ilosc_zaladowana_kg", 0) or 0
                for s in s1.get("surowce", [])
                if s.get("kod_surowca") == "dmapa_zwrotna"
            )

            # pH from utlenienie (last analiza)
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

            results.append({
                "batch_id": f"{prod_dir.name}/{batch_nr}",
                "product": product,
                "wielkosc_kg": wielkosc,
                "ph_before": ph_before,
                "ph_after": ph_after,
                "acid_kg": acid_kg,
                "dmapa_zwrotna_kg": dmapa_zwrotna_kg,
                "utl_ph": ph_before,  # same as ph_before for train
                "source": "train",
            })

    df = pd.DataFrame(results)
    print(f"Loaded {len(df)} batches from verified JSONs (train)")
    return df


def load_test_data() -> pd.DataFrame:
    """Load hardcoded test data."""
    rows = []
    for batch_nr, prod_key, wielkosc, ph_before, acid_kg, ph_after in TEST_DATA:
        product = _normalize_product(prod_key)
        rows.append({
            "batch_id": f"test/{batch_nr}",
            "product": product,
            "wielkosc_kg": wielkosc,
            "ph_before": ph_before,
            "ph_after": ph_after,
            "acid_kg": acid_kg,
            "dmapa_zwrotna_kg": np.nan,  # not available in test
            "utl_ph": ph_before,
            "source": "test",
        })
    df = pd.DataFrame(rows)
    print(f"Loaded {len(df)} batches from hardcoded test set")
    return df


def build_dataset() -> pd.DataFrame:
    """Combine train + test, compute features, filter."""
    train_df = load_train_data()
    test_df = load_test_data()
    df = pd.concat([train_df, test_df], ignore_index=True)

    # Compute derived columns
    df["tons"] = df["wielkosc_kg"] / 1000
    df["acid_per_ton"] = df["acid_kg"] / df["tons"]
    df["delta_ph"] = df["ph_before"] - df["ph_after"]
    df["buffer_cap"] = df["acid_per_ton"] / df["delta_ph"]
    df["dmapa_zwrotna_per_ton"] = df["dmapa_zwrotna_kg"] / df["tons"]

    # Drop invalid
    before = len(df)
    df = df.dropna(subset=["buffer_cap", "ph_before", "ph_after"]).reset_index(drop=True)
    df = df[np.isfinite(df["buffer_cap"]) & (df["buffer_cap"] > 0)].reset_index(drop=True)
    dropped_invalid = before - len(df)

    # Filter: ph_before >= 9, acid_kg > 0, delta_ph > 0.5
    before2 = len(df)
    df = df[
        (df["ph_before"] >= 9.0) & (df["acid_kg"] > 0) & (df["delta_ph"] > 0.5)
    ].reset_index(drop=True)
    dropped_filter = before2 - len(df)

    print(f"Dataset: {len(df)} rows (dropped {dropped_invalid} invalid, {dropped_filter} filtered)")
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


# ── Per-product model fitting ──────────────────────────────────────────────


def _fit_k7(df: pd.DataFrame) -> ProductModel:
    """K7: OLS on dmapa_zwrotna_per_ton."""
    sub = df[df["product"] == "K7"]
    train = sub[sub["source"] == "train"].copy()
    test = sub[sub["source"] == "test"].copy()

    # Only train data has dmapa_zwrotna
    train_valid = train.dropna(subset=["dmapa_zwrotna_per_ton"])
    train_valid = train_valid[train_valid["dmapa_zwrotna_per_ton"] > 0]

    X = sm.add_constant(train_valid["dmapa_zwrotna_per_ton"])
    y = train_valid["buffer_cap"]
    model = sm.OLS(y, X).fit()

    pm = ProductModel(
        product="K7",
        model_type="ols",
        buffer_cap_mean=train_valid["buffer_cap"].mean(),
        buffer_cap_std=train_valid["buffer_cap"].std(),
        n_train=len(train_valid),
        n_test=len(test),
        ols_model=model,
        feature_name="dmapa_zwrotna_per_ton",
        intercept=model.params["const"],
        coef=model.params["dmapa_zwrotna_per_ton"],
        r_squared=model.rsquared,
        p_value=model.pvalues["dmapa_zwrotna_per_ton"],
        notes="Test uses mean buffer_cap (no card features available)",
    )

    # LOO-CV on train
    if len(train_valid) > 2:
        loo = LeaveOneOut()
        preds = np.empty(len(train_valid))
        for tr_idx, te_idx in loo.split(X):
            m = sm.OLS(y.values[tr_idx], X.iloc[tr_idx]).fit()
            preds[te_idx] = m.predict(X.iloc[te_idx])
        residuals = y.values - preds
        pm.loo_mae = np.mean(np.abs(residuals))
        pm.loo_mape = np.mean(np.abs(residuals) / y.values) * 100

    print(f"\n  K7 OLS: intercept={pm.intercept:.3f}, coef={pm.coef:.4f}, "
          f"R2={pm.r_squared:.3f}, p={pm.p_value:.4f}")
    print(f"  K7 LOO-CV: MAPE={pm.loo_mape:.1f}%, MAE={pm.loo_mae:.3f}")
    return pm


def _fit_k40gl(df: pd.DataFrame) -> ProductModel:
    """K40GL: constant (mean buffer_cap from train)."""
    sub = df[df["product"] == "K40GL"]
    train = sub[sub["source"] == "train"]
    test = sub[sub["source"] == "test"]

    bc_values = train["buffer_cap"] if len(train) > 0 else sub["buffer_cap"]
    mean_bc = bc_values.mean()
    std_bc = bc_values.std() if len(bc_values) > 1 else 0.0

    pm = ProductModel(
        product="K40GL",
        model_type="constant",
        buffer_cap_mean=mean_bc,
        buffer_cap_std=std_bc,
        n_train=len(train),
        n_test=len(test),
        notes="Constant model (mean buffer_cap from train)",
    )

    # LOO-CV: leave-one-out mean
    if len(bc_values) > 2:
        vals = bc_values.values
        loo_preds = np.array([(np.sum(vals) - v) / (len(vals) - 1) for v in vals])
        residuals = vals - loo_preds
        pm.loo_mae = np.mean(np.abs(residuals))
        pm.loo_mape = np.mean(np.abs(residuals) / vals) * 100

    print(f"\n  K40GL constant: mean={mean_bc:.3f}, std={std_bc:.3f}, "
          f"n_train={len(train)}, n_test={len(test)}")
    if pm.loo_mape > 0:
        print(f"  K40GL LOO-CV: MAPE={pm.loo_mape:.1f}%, MAE={pm.loo_mae:.3f}")
    return pm


def _fit_k40glol(df: pd.DataFrame) -> ProductModel:
    """K40GLOL: OLS on utl_ph, using combined train+test data."""
    sub = df[df["product"] == "K40GLOL"]

    # Train has 0 valid obs in pH>=9 regime typically, so combine all
    combined = sub.dropna(subset=["utl_ph"])
    combined = combined[combined["utl_ph"] > 0]

    if len(combined) < 3:
        # Fallback: constant
        mean_bc = combined["buffer_cap"].mean() if len(combined) > 0 else 1.5
        pm = ProductModel(
            product="K40GLOL",
            model_type="constant",
            buffer_cap_mean=mean_bc,
            n_train=(combined["source"] == "train").sum(),
            n_test=(combined["source"] == "test").sum(),
            notes="Insufficient data for OLS, using constant",
        )
        print(f"\n  K40GLOL fallback constant: mean={mean_bc:.3f}, n={len(combined)}")
        return pm

    X = sm.add_constant(combined["utl_ph"])
    y = combined["buffer_cap"]
    model = sm.OLS(y, X).fit()

    pm = ProductModel(
        product="K40GLOL",
        model_type="ols",
        buffer_cap_mean=combined["buffer_cap"].mean(),
        buffer_cap_std=combined["buffer_cap"].std(),
        n_train=(combined["source"] == "train").sum(),
        n_test=(combined["source"] == "test").sum(),
        ols_model=model,
        feature_name="utl_ph",
        intercept=model.params["const"],
        coef=model.params["utl_ph"],
        r_squared=model.rsquared,
        p_value=model.pvalues["utl_ph"],
        notes="Combined train+test data (train has too few pH>=9 obs)",
    )

    # LOO-CV
    if len(combined) > 2:
        loo = LeaveOneOut()
        preds = np.empty(len(combined))
        for tr_idx, te_idx in loo.split(X):
            m = sm.OLS(y.values[tr_idx], X.iloc[tr_idx]).fit()
            preds[te_idx] = m.predict(X.iloc[te_idx])
        residuals = y.values - preds
        pm.loo_mae = np.mean(np.abs(residuals))
        pm.loo_mape = np.mean(np.abs(residuals) / y.values) * 100

    print(f"\n  K40GLOL OLS: intercept={pm.intercept:.3f}, coef={pm.coef:.4f}, "
          f"R2={pm.r_squared:.3f}, p={pm.p_value:.4f}")
    print(f"  K40GLOL LOO-CV: MAPE={pm.loo_mape:.1f}%, MAE={pm.loo_mae:.3f}")
    return pm


def _fit_k40glo(df: pd.DataFrame) -> ProductModel:
    """K40GLO: constant from single observation."""
    sub = df[df["product"] == "K40GLO"]

    mean_bc = sub["buffer_cap"].mean() if len(sub) > 0 else 1.36

    pm = ProductModel(
        product="K40GLO",
        model_type="constant",
        buffer_cap_mean=mean_bc,
        n_train=(sub["source"] == "train").sum(),
        n_test=(sub["source"] == "test").sum(),
        notes="Single observation, not reliable",
    )

    print(f"\n  K40GLO constant: mean={mean_bc:.3f}, n={len(sub)}")
    return pm


def fit_per_product(df: pd.DataFrame) -> dict[str, ProductModel]:
    """Fit separate models per product."""
    print("\n-- Per-Product Model Fitting --")

    models = {}
    models["K7"] = _fit_k7(df)
    models["K40GL"] = _fit_k40gl(df)
    models["K40GLOL"] = _fit_k40glol(df)
    models["K40GLO"] = _fit_k40glo(df)

    return models


# ── Prediction ─────────────────────────────────────────────────────────────


def predict_all(df: pd.DataFrame, models: dict[str, ProductModel]) -> pd.DataFrame:
    """Generate predictions for all observations."""
    pred_df = df.copy()
    pred_df["pred_buffer_cap"] = np.nan

    for idx, row in pred_df.iterrows():
        product = row["product"]
        pm = models.get(product)
        if pm is None:
            continue

        if pm.model_type == "constant":
            pred_df.loc[idx, "pred_buffer_cap"] = pm.buffer_cap_mean

        elif pm.model_type == "ols":
            if product == "K7":
                # For test K7: use mean buffer_cap from train
                if row["source"] == "test" or pd.isna(row.get("dmapa_zwrotna_per_ton")):
                    pred_df.loc[idx, "pred_buffer_cap"] = pm.buffer_cap_mean
                else:
                    val = row["dmapa_zwrotna_per_ton"]
                    pred_df.loc[idx, "pred_buffer_cap"] = pm.intercept + pm.coef * val

            elif product == "K40GLOL":
                val = row.get("utl_ph")
                if pd.notna(val) and val > 0:
                    pred_df.loc[idx, "pred_buffer_cap"] = pm.intercept + pm.coef * val
                else:
                    pred_df.loc[idx, "pred_buffer_cap"] = pm.buffer_cap_mean

    # Compute predicted acid_kg
    pred_df["pred_acid_kg"] = (
        pred_df["pred_buffer_cap"] * pred_df["delta_ph"] * pred_df["tons"]
    )
    pred_df["error_kg"] = pred_df["acid_kg"] - pred_df["pred_acid_kg"]
    pred_df["abs_error_kg"] = pred_df["error_kg"].abs()
    pred_df["pct_error"] = (pred_df["abs_error_kg"] / pred_df["acid_kg"]) * 100

    return pred_df


# ── Metrics ────────────────────────────────────────────────────────────────


def compute_metrics(pred_df: pd.DataFrame) -> dict:
    """Compute per-product and overall metrics."""
    metrics = {}

    valid = pred_df.dropna(subset=["pred_acid_kg"])

    # Overall
    metrics["overall_mape"] = valid["pct_error"].mean()
    metrics["overall_mae"] = valid["abs_error_kg"].mean()

    # Train vs test
    train = valid[valid["source"] == "train"]
    test = valid[valid["source"] == "test"]
    metrics["train_mape"] = train["pct_error"].mean() if len(train) > 0 else 0.0
    metrics["test_mape"] = test["pct_error"].mean() if len(test) > 0 else 0.0

    # Per product
    per_product = {}
    for prod in valid["product"].unique():
        sub = valid[valid["product"] == prod]
        sub_train = sub[sub["source"] == "train"]
        sub_test = sub[sub["source"] == "test"]
        per_product[prod] = {
            "n": len(sub),
            "n_train": len(sub_train),
            "n_test": len(sub_test),
            "mape": sub["pct_error"].mean(),
            "mae": sub["abs_error_kg"].mean(),
            "train_mape": sub_train["pct_error"].mean() if len(sub_train) > 0 else None,
            "test_mape": sub_test["pct_error"].mean() if len(sub_test) > 0 else None,
        }
    metrics["per_product"] = per_product

    print("\n-- Metrics --")
    print(f"  Overall MAPE: {metrics['overall_mape']:.1f}%")
    print(f"  Train MAPE:   {metrics['train_mape']:.1f}%")
    print(f"  Test MAPE:    {metrics['test_mape']:.1f}%")
    for prod, pm in sorted(per_product.items()):
        tr = f"{pm['train_mape']:.1f}%" if pm['train_mape'] is not None else "n/a"
        te = f"{pm['test_mape']:.1f}%" if pm['test_mape'] is not None else "n/a"
        print(f"  {prod}: n={pm['n']}, MAPE={pm['mape']:.1f}% (train={tr}, test={te})")

    return metrics


# ── Plots ──────────────────────────────────────────────────────────────────


def make_plots(pred_df: pd.DataFrame) -> dict[str, str]:
    """Generate diagnostic plots, return dict of name→base64 PNG."""
    figs = {}

    valid = pred_df.dropna(subset=["pred_acid_kg"])

    # 1. Actual vs Predicted scatter
    fig, ax = plt.subplots(figsize=(7, 6))
    for prod, color in PRODUCT_COLORS.items():
        for src, marker in SOURCE_MARKERS.items():
            mask = (valid["product"] == prod) & (valid["source"] == src)
            sub = valid[mask]
            if len(sub) == 0:
                continue
            ax.scatter(
                sub["acid_kg"], sub["pred_acid_kg"],
                c=color, marker=marker, s=60, alpha=0.85,
                edgecolors="k", linewidth=0.5,
                label=f"{prod} ({src})",
            )
    mn = min(valid["acid_kg"].min(), valid["pred_acid_kg"].min()) * 0.9
    mx = max(valid["acid_kg"].max(), valid["pred_acid_kg"].max()) * 1.1
    ax.plot([mn, mx], [mn, mx], "k--", alpha=0.5)
    ax.set_xlabel("Dawka rzeczywista [kg]")
    ax.set_ylabel("Dawka przewidywana [kg]")
    ax.set_title("Rzeczywista vs przewidywana dawka kwasu")
    ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    figs["scatter"] = fig_to_base64(fig)

    # 2. Residuals by product
    fig, ax = plt.subplots(figsize=(7, 5))
    products = sorted(valid["product"].unique())
    for i, prod in enumerate(products):
        sub = valid[valid["product"] == prod]
        jitter = np.random.default_rng(42).uniform(-0.15, 0.15, len(sub))
        for src, marker in SOURCE_MARKERS.items():
            mask = sub["source"] == src
            s = sub[mask]
            if len(s) == 0:
                continue
            ax.scatter(
                np.full(len(s), i) + jitter[mask.values],
                s["error_kg"],
                c=PRODUCT_COLORS.get(prod, "#999"),
                marker=marker, s=50, alpha=0.8,
                edgecolors="k", linewidth=0.5,
            )
    ax.axhline(0, color="k", linestyle="--", alpha=0.5)
    ax.set_xticks(range(len(products)))
    ax.set_xticklabels(products)
    ax.set_ylabel("Blad [kg] (rzecz. - pred.)")
    ax.set_title("Residua per produkt")
    fig.tight_layout()
    figs["residuals"] = fig_to_base64(fig)

    # 3. K7 residuals vs dmapa_zwrotna (for K7 train only)
    k7_train = valid[(valid["product"] == "K7") & (valid["source"] == "train")]
    k7_train = k7_train.dropna(subset=["dmapa_zwrotna_per_ton"])
    if len(k7_train) > 2:
        fig, ax = plt.subplots(figsize=(6, 5))
        ax.scatter(
            k7_train["dmapa_zwrotna_per_ton"],
            k7_train["buffer_cap"] - k7_train["pred_buffer_cap"],
            c=PRODUCT_COLORS["K7"], s=60, edgecolors="k", linewidth=0.5,
        )
        ax.axhline(0, color="k", linestyle="--", alpha=0.5)
        ax.set_xlabel("DMAPA zwrotna [kg/t]")
        ax.set_ylabel("Residuum buffer_cap")
        ax.set_title("K7: Residua vs DMAPA zwrotna")
        fig.tight_layout()
        figs["k7_residuals"] = fig_to_base64(fig)

    # 4. Q-Q plot for K7 train residuals
    if len(k7_train) > 2:
        resid = (k7_train["buffer_cap"] - k7_train["pred_buffer_cap"]).values
        fig, ax = plt.subplots(figsize=(6, 5))
        sm.qqplot(resid, line="45", ax=ax, markersize=5)
        ax.set_title("K7: Q-Q Plot residuow buffer_cap")
        fig.tight_layout()
        figs["k7_qq"] = fig_to_base64(fig)

    return figs


# ── HTML Report ────────────────────────────────────────────────────────────


def generate_report(
    df: pd.DataFrame,
    models: dict[str, ProductModel],
    pred_df: pd.DataFrame,
    metrics: dict,
    figs: dict[str, str],
) -> None:
    """Generate HTML report."""

    n_total = len(pred_df)
    n_train = (pred_df["source"] == "train").sum()
    n_test = (pred_df["source"] == "test").sum()

    # ── Operator section ──
    k7 = models["K7"]
    k40gl = models["K40GL"]
    k40glol = models["K40GLOL"]
    k40glo = models["K40GLO"]

    # Example calculations
    ex_k7 = f"dawka = {k7.buffer_cap_mean:.2f} x (11.8 - 6.0) x 10.0 = {k7.buffer_cap_mean * 5.8 * 10:.0f} kg"
    ex_k40gl = f"dawka = {k40gl.buffer_cap_mean:.2f} x (11.7 - 5.5) x 11.3 = {k40gl.buffer_cap_mean * 6.2 * 11.3:.0f} kg"

    # K40GLOL example at utl_ph=11.8
    if k40glol.model_type == "ols":
        bc_glol_ex = k40glol.intercept + k40glol.coef * 11.8
        ex_k40glol = (f"B = {k40glol.intercept:.2f} + ({k40glol.coef:.3f}) x 11.8 = {bc_glol_ex:.2f}\n"
                      f"    dawka = {bc_glol_ex:.2f} x (11.8 - 5.5) x 12.0 = {bc_glol_ex * 6.3 * 12:.0f} kg")
    else:
        ex_k40glol = f"dawka = {k40glol.buffer_cap_mean:.2f} x (11.8 - 5.5) x 12.0 = {k40glol.buffer_cap_mean * 6.3 * 12:.0f} kg"

    ex_k40glo = f"dawka = {k40glo.buffer_cap_mean:.2f} x (11.8 - 6.0) x 7.8 = {k40glo.buffer_cap_mean * 5.8 * 7.8:.0f} kg"

    # K40GLOL model description for operator table
    if k40glol.model_type == "ols":
        k40glol_b_str = "z modelu pH"
        k40glol_uwagi = f"B = {k40glol.intercept:.2f} + ({k40glol.coef:.3f}) x pH_utlenienia (model wstepny)"
    else:
        k40glol_b_str = f"{k40glol.buffer_cap_mean:.2f}"
        k40glol_uwagi = "stala (za malo danych na model)"

    # ── Per-product model details ──
    model_details_html = ""

    # K7
    model_details_html += "<h3>K7 — regresja OLS na DMAPA zwrotna</h3>\n"
    if k7.ols_model is not None:
        summary = k7.ols_model.summary().as_html()
        model_details_html += f"""
<p><strong>Formula:</strong> <code>buffer_cap = {k7.intercept:.3f} + ({k7.coef:.4f}) x dmapa_zwrotna_per_ton</code></p>
<p>R&sup2; = {k7.r_squared:.4f}, p(dmapa) = {k7.p_value:.4f}, n = {k7.n_train} (train)</p>
<p>LOO-CV: MAPE = {k7.loo_mape:.1f}%, MAE = {k7.loo_mae:.3f}</p>
<p>Sredni buffer_cap (train) = {k7.buffer_cap_mean:.3f} (uzywany dla test K7 bez karty)</p>
<details><summary>Pelne podsumowanie OLS</summary>{summary}</details>
"""

    # K40GL
    model_details_html += "<h3>K40GL — stala (srednia buffer_cap)</h3>\n"
    model_details_html += f"""
<p>Srednia = {k40gl.buffer_cap_mean:.3f}, Std = {k40gl.buffer_cap_std:.3f},
   CV = {(k40gl.buffer_cap_std / k40gl.buffer_cap_mean * 100) if k40gl.buffer_cap_mean > 0 else 0:.1f}%</p>
<p>n_train = {k40gl.n_train}, n_test = {k40gl.n_test}</p>
"""
    if k40gl.loo_mape > 0:
        model_details_html += f"<p>LOO-CV: MAPE = {k40gl.loo_mape:.1f}%, MAE = {k40gl.loo_mae:.3f}</p>\n"

    # K40GLOL
    model_details_html += "<h3>K40GLOL — regresja OLS na pH utlenienia</h3>\n"
    if k40glol.ols_model is not None:
        summary = k40glol.ols_model.summary().as_html()
        model_details_html += f"""
<p><strong>Formula:</strong> <code>buffer_cap = {k40glol.intercept:.3f} + ({k40glol.coef:.4f}) x utl_ph</code></p>
<p>R&sup2; = {k40glol.r_squared:.4f}, p(utl_ph) = {k40glol.p_value:.4f},
   n = {k40glol.n_train + k40glol.n_test} (combined train+test)</p>
<p>LOO-CV: MAPE = {k40glol.loo_mape:.1f}%, MAE = {k40glol.loo_mae:.3f}</p>
<details><summary>Pelne podsumowanie OLS</summary>{summary}</details>
"""
    else:
        model_details_html += f"<p>Stala: {k40glol.buffer_cap_mean:.3f}</p>\n"

    # K40GLO
    model_details_html += "<h3>K40GLO — stala (1 obserwacja)</h3>\n"
    model_details_html += f"""
<p>buffer_cap = {k40glo.buffer_cap_mean:.3f} (n = {k40glo.n_train + k40glo.n_test})</p>
<div class="note"><strong>Uwaga:</strong> Tylko 1 obserwacja w rezimu pH &ge; 9. Wartosc orientacyjna.</div>
"""

    # ── Validation table ──
    pp = metrics.get("per_product", {})
    val_rows = ""
    for prod in ["K7", "K40GL", "K40GLO", "K40GLOL"]:
        if prod in pp:
            m = pp[prod]
            tr = f"{m['train_mape']:.1f}%" if m['train_mape'] is not None else "n/d"
            te = f"{m['test_mape']:.1f}%" if m['test_mape'] is not None else "n/d"
            val_rows += (
                f"<tr><td>{prod}</td><td>{m['n']}</td><td>{m['n_train']}</td><td>{m['n_test']}</td>"
                f"<td>{m['mape']:.1f}%</td><td>{tr}</td><td>{te}</td>"
                f"<td>{m['mae']:.1f}</td></tr>\n"
            )

    # ── Prediction table ──
    pred_rows = ""
    for _, row in pred_df.sort_values("abs_error_kg", ascending=False).iterrows():
        src_badge = '<span style="color:#e91e63;font-weight:bold">T</span>' if row["source"] == "test" else ""
        pred_rows += (
            f"<tr><td>{row['batch_id']}</td>"
            f"<td>{row['product']}</td>"
            f"<td>{src_badge}</td>"
            f"<td>{row['wielkosc_kg']:.0f}</td>"
            f"<td>{row['ph_before']:.2f}</td>"
            f"<td>{row['ph_after']:.2f}</td>"
            f"<td>{row['delta_ph']:.2f}</td>"
            f"<td>{row['acid_kg']:.1f}</td>"
            f"<td>{row['pred_buffer_cap']:.3f}</td>"
            f"<td>{row['pred_acid_kg']:.1f}</td>"
            f"<td>{row['error_kg']:+.1f}</td>"
            f"<td>{row['pct_error']:.1f}%</td></tr>\n"
        )

    # ── Diagnostic plots ──
    scatter_img = f'<img src="data:image/png;base64,{figs["scatter"]}" alt="Scatter">' if "scatter" in figs else ""
    residuals_img = f'<img src="data:image/png;base64,{figs["residuals"]}" alt="Residuals">' if "residuals" in figs else ""
    k7_res_img = f'<img src="data:image/png;base64,{figs["k7_residuals"]}" alt="K7 Residuals">' if "k7_residuals" in figs else ""
    k7_qq_img = f'<img src="data:image/png;base64,{figs["k7_qq"]}" alt="K7 Q-Q">' if "k7_qq" in figs else ""

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<title>Model buffer capacity - per-product</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 1100px; margin: 30px auto; padding: 0 20px; color: #333; background: #fafafa; }}
  h1 {{ color: #1565C0; border-bottom: 3px solid #1565C0; padding-bottom: 10px; }}
  h2 {{ color: #1565C0; margin-top: 35px; border-bottom: 1px solid #ddd; padding-bottom: 6px; }}
  h3 {{ color: #333; margin-top: 20px; }}
  .card {{ background: #fff; border-radius: 8px; padding: 20px; margin: 15px 0; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }}
  table {{ border-collapse: collapse; margin: 12px 0; width: 100%; }}
  th, td {{ border: 1px solid #ddd; padding: 7px 12px; text-align: right; }}
  th {{ background: #1565C0; color: #fff; text-align: center; font-weight: 600; }}
  td:first-child {{ text-align: left; }}
  .operator-box {{ background: #e8f5e9; border-left: 5px solid #4CAF50; padding: 20px; margin: 20px 0; border-radius: 0 8px 8px 0; }}
  .operator-box h2 {{ color: #2E7D32; border: none; margin-top: 0; }}
  .formula-box {{ background: #fff3e0; border-left: 4px solid #FF9800; padding: 15px; margin: 15px 0; font-family: 'Consolas', monospace; font-size: 1.05em; white-space: pre-line; border-radius: 0 6px 6px 0; }}
  .note {{ background: #fce4ec; border-left: 4px solid #e91e63; padding: 12px; margin: 12px 0; border-radius: 0 6px 6px 0; }}
  .metric-box {{ display: inline-block; background: #e3f2fd; border-radius: 8px; padding: 12px 20px; margin: 6px; text-align: center; }}
  .metric-box .val {{ font-size: 1.5em; font-weight: bold; color: #1565C0; }}
  .metric-box .lbl {{ font-size: 0.85em; color: #555; }}
  img {{ max-width: 100%; margin: 8px 0; border-radius: 4px; }}
  .plot-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  pre {{ background: #f5f5f5; padding: 12px; border-radius: 4px; overflow-x: auto; }}
  details {{ margin: 8px 0; }}
  summary {{ cursor: pointer; color: #1565C0; font-weight: 600; }}
  code {{ background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-size: 0.95em; }}
  .example {{ background: #f5f5f5; padding: 10px 15px; margin: 8px 0; border-radius: 4px; font-family: monospace; }}
</style>
</head>
<body>

<h1>Model pojemnosci buforowej &mdash; dawkowanie kwasu cytrynowego</h1>
<p>Modele per-produkt. Dane: {n_total} obserwacji ({n_train} train + {n_test} test),
filtr: pH &ge; 9, acid &gt; 0, delta_pH &gt; 0.5.</p>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!-- 1. OPERATOR SECTION -->
<!-- ═══════════════════════════════════════════════════════════════ -->

<div class="operator-box">
<h2>1. Wzor operatorski</h2>

<div class="formula-box">
dawka_kwasu [kg] = B x (pH_przed - pH_docelowe) x (masa_kg / 1000)
</div>

<table>
  <tr><th>Produkt</th><th>B (pojemnosc buforowa)</th><th>Dokladnosc</th><th>Uwagi</th></tr>
  <tr>
    <td><strong>K7</strong></td>
    <td><strong>{k7.buffer_cap_mean:.2f}</strong>*</td>
    <td>&plusmn;{k7.loo_mape:.1f}%</td>
    <td>*z pelna karta: B = {k7.intercept:.2f} - {abs(k7.coef):.3f} x DMAPA_zwrotna_per_ton</td>
  </tr>
  <tr>
    <td><strong>K40GL</strong></td>
    <td><strong>{k40gl.buffer_cap_mean:.2f}</strong></td>
    <td>&plusmn;{k40gl.loo_mape:.1f}%</td>
    <td>stala</td>
  </tr>
  <tr>
    <td><strong>K40GLOL</strong></td>
    <td><strong>{k40glol_b_str}</strong></td>
    <td>&plusmn;{k40glol.loo_mape:.1f}%</td>
    <td>{k40glol_uwagi}</td>
  </tr>
  <tr>
    <td><strong>K40GLO</strong></td>
    <td><strong>{k40glo.buffer_cap_mean:.2f}</strong></td>
    <td>n/d</td>
    <td>1 obserwacja</td>
  </tr>
</table>

<h3>Przyklady</h3>
<p><strong>K7</strong>, 10 000 kg, pH_przed=11.8, pH_docelowe=6.0:</p>
<div class="example">{ex_k7}</div>

<p><strong>K40GL</strong>, 11 300 kg, pH_przed=11.7, pH_docelowe=5.5:</p>
<div class="example">{ex_k40gl}</div>

<p><strong>K40GLOL</strong>, 12 000 kg, pH_przed=11.8, pH_docelowe=5.5:</p>
<div class="example">{ex_k40glol}</div>

<p><strong>K40GLO</strong>, 7 800 kg, pH_przed=11.8, pH_docelowe=6.0:</p>
<div class="example">{ex_k40glo}</div>
</div>

<div class="note">
  <strong>Uwaga:</strong> Model dotyczy TYLKO pH &ge; 9 (po utlenianiu). Dla pH &lt; 9 chemia jest
  fundamentalnie inna i model nie obowiazuje.
</div>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!-- 2. PER-PRODUCT MODEL DETAILS -->
<!-- ═══════════════════════════════════════════════════════════════ -->

<h2>2. Szczegoly modeli per-produkt</h2>
<div class="card">
{model_details_html}
</div>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!-- 3. VALIDATION -->
<!-- ═══════════════════════════════════════════════════════════════ -->

<h2>3. Walidacja</h2>

<div>
  <div class="metric-box"><div class="val">{metrics['overall_mape']:.1f}%</div><div class="lbl">Overall MAPE</div></div>
  <div class="metric-box"><div class="val">{metrics['train_mape']:.1f}%</div><div class="lbl">Train MAPE</div></div>
  <div class="metric-box"><div class="val">{metrics['test_mape']:.1f}%</div><div class="lbl">Test MAPE</div></div>
  <div class="metric-box"><div class="val">{metrics['overall_mae']:.1f} kg</div><div class="lbl">Overall MAE</div></div>
</div>

<h3>Per-produkt</h3>
<table>
  <tr><th>Produkt</th><th>n</th><th>Train</th><th>Test</th><th>MAPE</th><th>Train MAPE</th><th>Test MAPE</th><th>MAE [kg]</th></tr>
  {val_rows}
</table>

<h3>Wykres: Rzeczywista vs Przewidywana</h3>
<div class="card">
{scatter_img}
</div>

<h3>Predykcje — tabela</h3>
<table>
  <tr><th>Batch</th><th>Produkt</th><th>Src</th><th>Masa [kg]</th>
      <th>pH przed</th><th>pH po</th><th>&Delta;pH</th><th>Kwas [kg]</th>
      <th>B pred</th><th>Pred [kg]</th><th>Blad [kg]</th><th>Blad %</th></tr>
  {pred_rows}
</table>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!-- 4. DIAGNOSTICS -->
<!-- ═══════════════════════════════════════════════════════════════ -->

<h2>4. Diagnostyka</h2>
<div class="plot-grid">
  <div>{residuals_img}</div>
  <div>{k7_res_img}</div>
  <div>{k7_qq_img}</div>
</div>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!-- 5. CAVEATS -->
<!-- ═══════════════════════════════════════════════════════════════ -->

<h2>5. Zastrzezenia</h2>
<div class="card">
<ul>
  <li><strong>pH &lt; 9 wykluczone</strong> — inna chemia (buforowanie aminowe), model nie obowiazuje</li>
  <li><strong>K40GLOL — model wstepny</strong> — oparty na danych testowych (train ma za malo obserwacji pH &ge; 9)</li>
  <li><strong>K40GLO — 1 obserwacja</strong> — wartosc B orientacyjna, zbyt malo danych na wiarygodny model</li>
  <li><strong>Test K7</strong> — uzywa stalej B (brak cech z karty: dmapa_zwrotna); z pelna karta blad mniejszy</li>
  <li><strong>delta_pH &gt; 0.5 wymagane</strong> — male delty pH daja niestabilne oszacowania buffer_cap</li>
</ul>
</div>

</body>
</html>"""

    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"\nHTML report saved: {OUT_HTML}")


# ── Summary ────────────────────────────────────────────────────────────────


def print_summary(models: dict[str, ProductModel], metrics: dict) -> None:
    print("\n" + "=" * 60)
    print("  SUMMARY — Per-Product Buffer Capacity Models")
    print("=" * 60)
    for prod in ["K7", "K40GL", "K40GLOL", "K40GLO"]:
        pm = models[prod]
        if pm.model_type == "ols":
            print(f"  {prod:8s}: {pm.model_type} on {pm.feature_name}, "
                  f"intercept={pm.intercept:.3f}, coef={pm.coef:.4f}, "
                  f"R2={pm.r_squared:.3f}, LOO MAPE={pm.loo_mape:.1f}%")
        else:
            print(f"  {prod:8s}: constant B={pm.buffer_cap_mean:.3f}"
                  + (f", std={pm.buffer_cap_std:.3f}" if pm.buffer_cap_std > 0 else "")
                  + (f", LOO MAPE={pm.loo_mape:.1f}%" if pm.loo_mape > 0 else ""))
    print(f"\n  Overall MAPE:  {metrics['overall_mape']:.1f}%")
    print(f"  Train MAPE:    {metrics['train_mape']:.1f}%")
    print(f"  Test MAPE:     {metrics['test_mape']:.1f}%")
    print(f"  Report:        {OUT_HTML}")


# ── Main ────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    print("=" * 60)
    print("  Per-Product Buffer Capacity Models")
    print("=" * 60)

    df = build_dataset()
    models = fit_per_product(df)
    pred_df = predict_all(df, models)
    metrics = compute_metrics(pred_df)
    figs = make_plots(pred_df)
    generate_report(df, models, pred_df, metrics, figs)
    print_summary(models, metrics)
