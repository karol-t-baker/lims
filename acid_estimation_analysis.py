"""
Acid estimation model for K7 chegina — buffer capacity approach.

Predicts citric acid dosage (kg) for target pH 6.25 using buffer capacity:
  buffer_cap = kwas_per_eff_ton / delta_ph  [kg acid / ton solution / pH unit]

Compares: OLS linear, polynomial (deg 2, 3), Ridge-regularized models.
Validates with LOOCV. Generates diagnostic plots.

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
from scipy import stats
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut
from sklearn.neighbors import KNeighborsRegressor
from sklearn.preprocessing import PolynomialFeatures, StandardScaler


TARGET_PH = 6.25


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
    """Compute effective mass, buffer capacity, and normalized features."""
    df = df.copy()
    df["woda_refrakcja"] = df["woda_kg"] - df["kwas_kg"]
    df["masa_efektywna"] = df["masa_kg"] + df["woda_refrakcja"]
    df["masa_eff_ton"] = df["masa_efektywna"] / 1000.0
    df["kwas_per_eff_ton"] = df["kwas_kg"] / df["masa_eff_ton"]
    df["delta_ph"] = df["ph_start"] - df["ph_koniec"]
    df["buffer_cap"] = df["kwas_per_eff_ton"] / df["delta_ph"]
    df["h3o_scaled"] = 10.0 ** (12.0 - df["ph_start"])  # [H3O+] * 10^12
    return df


def _fit_single(X_train, bc_train, X_test, model_type, degree, alpha, n_neighbors):
    """Fit one model on train, predict on test. Returns bc predictions."""
    if model_type == "knn":
        model = KNeighborsRegressor(n_neighbors=n_neighbors, weights="distance")
        model.fit(X_train, bc_train)
        return model.predict(X_test)
    elif model_type == "ridge":
        model = Ridge(alpha=alpha)
        model.fit(X_train, bc_train)
        return model.predict(X_test)
    else:
        X_train_c = sm.add_constant(X_train)
        X_test_c = sm.add_constant(X_test, has_constant=False)
        model = sm.OLS(bc_train, X_train_c).fit()
        return model.predict(X_test_c)


def _make_features(values, degree):
    """Build feature matrix from 1D values."""
    if degree > 1:
        poly = PolynomialFeatures(degree, include_bias=False)
        return poly.fit_transform(values.reshape(-1, 1)), poly
    return values.reshape(-1, 1), None


def _loocv_predict_bc(ph_train, bc_train, ph_test, model_type, degree, alpha,
                      n_neighbors, ensemble, boosted, stacked):
    """Predict buffer capacity for one LOOCV fold."""
    if boosted is not None:
        # Stage 1: fit base model, get residuals
        base = boosted["base"]
        base_deg = base.get("degree", 1)
        Xtr_b, poly_b = _make_features(ph_train, base_deg)
        if poly_b:
            Xte_b = poly_b.transform(ph_test.reshape(-1, 1))
        else:
            Xte_b = ph_test.reshape(-1, 1)
        bc_base_train = _fit_single(Xtr_b, bc_train, Xtr_b,
                                    base["model_type"], base_deg,
                                    base.get("alpha", 1.0),
                                    base.get("n_neighbors", 5))
        bc_base_test = _fit_single(Xtr_b, bc_train, Xte_b,
                                   base["model_type"], base_deg,
                                   base.get("alpha", 1.0),
                                   base.get("n_neighbors", 5))
        # Stage 2: fit corrector on residuals
        residuals = bc_train - bc_base_train
        corr = boosted["corrector"]
        corr_deg = corr.get("degree", 1)
        Xtr_c, poly_c = _make_features(ph_train, corr_deg)
        if poly_c:
            Xte_c = poly_c.transform(ph_test.reshape(-1, 1))
        else:
            Xte_c = ph_test.reshape(-1, 1)
        bc_corr = _fit_single(Xtr_c, residuals, Xte_c,
                              corr["model_type"], corr_deg,
                              corr.get("alpha", 1.0),
                              corr.get("n_neighbors", 5))
        return bc_base_test + bc_corr

    if stacked is not None:
        # Stage 1: get base model predictions on train (inner LOOCV)
        base_models = stacked["base_models"]
        meta_cfg = stacked.get("meta", {"alpha": 1.0})
        n_train = len(ph_train)
        oof_preds = np.zeros((n_train, len(base_models)))
        test_preds = np.zeros(len(base_models))

        for m_idx, bm in enumerate(base_models):
            bm_deg = bm.get("degree", 1)
            # Full train prediction for test point
            Xtr_full, poly_full = _make_features(ph_train, bm_deg)
            if poly_full:
                Xte_full = poly_full.transform(ph_test.reshape(-1, 1))
            else:
                Xte_full = ph_test.reshape(-1, 1)
            test_preds[m_idx] = _fit_single(Xtr_full, bc_train, Xte_full,
                                            bm["model_type"], bm_deg,
                                            bm.get("alpha", 1.0),
                                            bm.get("n_neighbors", 5))[0]
            # Inner LOOCV for OOF predictions
            inner_loo = LeaveOneOut()
            for itr, ite in inner_loo.split(ph_train):
                Xtr_i, poly_i = _make_features(ph_train[itr], bm_deg)
                if poly_i:
                    Xte_i = poly_i.transform(ph_train[ite].reshape(-1, 1))
                else:
                    Xte_i = ph_train[ite].reshape(-1, 1)
                oof_preds[ite, m_idx] = _fit_single(Xtr_i, bc_train[itr], Xte_i,
                                                    bm["model_type"], bm_deg,
                                                    bm.get("alpha", 1.0),
                                                    bm.get("n_neighbors", 5))[0]
        # Stage 2: fit meta-learner on OOF predictions
        meta = Ridge(alpha=meta_cfg.get("alpha", 1.0))
        meta.fit(oof_preds, bc_train)
        return meta.predict(test_preds.reshape(1, -1))

    if ensemble is not None:
        bc_preds = []
        for sub in ensemble:
            sub_deg = sub.get("degree", 1)
            Xtr, poly_s = _make_features(ph_train, sub_deg)
            if poly_s:
                Xte = poly_s.transform(ph_test.reshape(-1, 1))
            else:
                Xte = ph_test.reshape(-1, 1)
            bc_p = _fit_single(Xtr, bc_train, Xte,
                               sub["model_type"], sub_deg,
                               sub.get("alpha", 1.0),
                               sub.get("n_neighbors", 5))
            bc_preds.append(bc_p[0])
        return np.array([np.mean(bc_preds)])

    X_train, poly = _make_features(ph_train, degree)
    if poly:
        X_test = poly.transform(ph_test.reshape(-1, 1))
    else:
        X_test = ph_test.reshape(-1, 1)
    return _fit_single(X_train, bc_train, X_test,
                       model_type, degree, alpha, n_neighbors)


def run_loocv(df: pd.DataFrame, model_type: str = "ols", degree: int = 1,
              alpha: float = 1.0, n_neighbors: int = 5,
              ensemble: list[dict] | None = None,
              boosted: dict | None = None,
              stacked: dict | None = None,
              feature: str = "ph_start") -> dict:
    """LOOCV predicting kwas_kg. Returns MAE, MAPE, R² CV, residuals, predictions."""
    ph = df[feature].values
    buffer_cap = df["buffer_cap"].values
    masa_eff_ton = df["masa_eff_ton"].values
    actual_kg = df["kwas_kg"].values
    delta_ph = df["delta_ph"].values
    loo = LeaveOneOut()

    pred_kg = np.zeros(len(ph))
    for train_idx, test_idx in loo.split(ph):
        ph_train, ph_test = ph[train_idx], ph[test_idx]
        bc_train = buffer_cap[train_idx]

        bc_pred = _loocv_predict_bc(ph_train, bc_train, ph_test,
                                    model_type, degree, alpha, n_neighbors,
                                    ensemble, boosted, stacked)

        # Use actual delta_ph for validation (not TARGET_PH)
        pred_kg[test_idx] = bc_pred * delta_ph[test_idx] * masa_eff_ton[test_idx]

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


def fit_full_model(df: pd.DataFrame, model_type: str = "ols", degree: int = 1,
                   alpha: float = 1.0, n_neighbors: int = 5,
                   ensemble: list[dict] | None = None,
                   boosted: dict | None = None,
                   stacked: dict | None = None,
                   feature: str = "ph_start") -> dict:
    """Fit buffer_cap ~ f(feature) on all data. Returns model info."""
    ph = df[feature].values
    bc = df["buffer_cap"].values

    if boosted is not None:
        base_fit = fit_full_model(df, **boosted["base"])
        bc_base = _predict_bc(base_fit, ph)
        residuals = bc - bc_base
        # Fit corrector on residuals — create a temp df-like structure
        corr_cfg = boosted["corrector"]
        corr_deg = corr_cfg.get("degree", 1)
        X_corr, poly_corr = _make_features(ph, corr_deg)
        if corr_cfg["model_type"] == "knn":
            corr_model = KNeighborsRegressor(
                n_neighbors=corr_cfg.get("n_neighbors", 5), weights="distance")
            corr_model.fit(X_corr, residuals)
        elif corr_cfg["model_type"] == "ridge":
            corr_model = Ridge(alpha=corr_cfg.get("alpha", 1.0))
            corr_model.fit(X_corr, residuals)
        else:
            X_corr_c = sm.add_constant(X_corr)
            corr_model = sm.OLS(residuals, X_corr_c).fit()
        bc_total = bc_base + (corr_model.predict(X_corr) if corr_cfg["model_type"] != "ols"
                              else corr_model.predict(sm.add_constant(X_corr)))
        ss_res = np.sum((bc - bc_total) ** 2)
        ss_tot = np.sum((bc - np.mean(bc)) ** 2)
        r2 = 1.0 - ss_res / ss_tot
        return {
            "base_fit": base_fit, "corr_model": corr_model,
            "corr_poly": poly_corr, "corr_type": corr_cfg["model_type"],
            "r_squared": r2, "type": "boosted", "degree": 0,
        }

    if stacked is not None:
        base_models_cfg = stacked["base_models"]
        meta_cfg = stacked.get("meta", {"alpha": 1.0})
        base_fits = [fit_full_model(df, **bm) for bm in base_models_cfg]
        # OOF predictions via inner LOOCV
        n = len(ph)
        oof = np.zeros((n, len(base_fits)))
        loo = LeaveOneOut()
        for tr, te in loo.split(ph):
            for m_idx, bm in enumerate(base_models_cfg):
                bm_deg = bm.get("degree", 1)
                Xtr, poly_i = _make_features(ph[tr], bm_deg)
                if poly_i:
                    Xte = poly_i.transform(ph[te].reshape(-1, 1))
                else:
                    Xte = ph[te].reshape(-1, 1)
                oof[te, m_idx] = _fit_single(Xtr, bc[tr], Xte,
                                             bm["model_type"], bm_deg,
                                             bm.get("alpha", 1.0),
                                             bm.get("n_neighbors", 5))[0]
        meta_model = Ridge(alpha=meta_cfg.get("alpha", 1.0))
        meta_model.fit(oof, bc)
        # R² on train using full base_fits
        base_preds = np.column_stack([_predict_bc(bf, ph) for bf in base_fits])
        bc_meta = meta_model.predict(base_preds)
        ss_res = np.sum((bc - bc_meta) ** 2)
        ss_tot = np.sum((bc - np.mean(bc)) ** 2)
        r2 = 1.0 - ss_res / ss_tot
        return {
            "base_fits": base_fits, "meta_model": meta_model,
            "r_squared": r2, "type": "stacked", "degree": 0,
        }

    if ensemble is not None:
        sub_models = []
        for sub in ensemble:
            sub_fit = fit_full_model(df, **sub)
            sub_models.append(sub_fit)
        bc_preds = []
        for sub_fit in sub_models:
            bc_preds.append(_predict_bc(sub_fit, ph))
        bc_avg = np.mean(bc_preds, axis=0)
        ss_res = np.sum((bc - bc_avg) ** 2)
        ss_tot = np.sum((bc - np.mean(bc)) ** 2)
        r2 = 1.0 - ss_res / ss_tot
        return {
            "sub_models": sub_models, "r_squared": r2,
            "type": "ensemble", "degree": 0,
        }

    if degree > 1:
        poly = PolynomialFeatures(degree, include_bias=False)
        X = poly.fit_transform(ph.reshape(-1, 1))
    else:
        poly = None
        X = ph.reshape(-1, 1)

    if model_type == "knn":
        model = KNeighborsRegressor(n_neighbors=n_neighbors, weights="distance")
        model.fit(X, bc)
        bc_pred = model.predict(X)
        ss_res = np.sum((bc - bc_pred) ** 2)
        ss_tot = np.sum((bc - np.mean(bc)) ** 2)
        r2 = 1.0 - ss_res / ss_tot
        return {
            "model": model, "poly": poly, "r_squared": r2,
            "type": "knn", "degree": degree, "n_neighbors": n_neighbors,
        }
    elif model_type == "ridge":
        model = Ridge(alpha=alpha)
        model.fit(X, bc)
        bc_pred = model.predict(X)
        ss_res = np.sum((bc - bc_pred) ** 2)
        ss_tot = np.sum((bc - np.mean(bc)) ** 2)
        r2 = 1.0 - ss_res / ss_tot
        return {
            "model": model, "poly": poly, "r_squared": r2,
            "type": "ridge", "degree": degree, "alpha": alpha,
        }
    else:
        X_c = sm.add_constant(X)
        ols_model = sm.OLS(bc, X_c).fit()
        return {
            "model": ols_model, "poly": poly,
            "r_squared": ols_model.rsquared,
            "r_squared_adj": ols_model.rsquared_adj,
            "coefficients": ols_model.params.tolist(),
            "p_values": ols_model.pvalues.tolist(),
            "type": "ols", "degree": degree,
        }


def _predict_bc(fit_result: dict, ph_values: np.ndarray) -> np.ndarray:
    """Predict buffer capacity for an array of pH values."""
    if fit_result["type"] == "boosted":
        bc_base = _predict_bc(fit_result["base_fit"], ph_values)
        ph_arr = ph_values.reshape(-1, 1)
        if fit_result.get("corr_poly") is not None:
            ph_arr = fit_result["corr_poly"].transform(ph_arr)
        if fit_result["corr_type"] == "ols":
            bc_corr = fit_result["corr_model"].predict(sm.add_constant(ph_arr, has_constant=False))
        else:
            bc_corr = fit_result["corr_model"].predict(ph_arr)
        return bc_base + bc_corr

    if fit_result["type"] == "stacked":
        base_preds = np.column_stack([_predict_bc(bf, ph_values)
                                      for bf in fit_result["base_fits"]])
        return fit_result["meta_model"].predict(base_preds)

    if fit_result["type"] == "ensemble":
        preds = [_predict_bc(sub, ph_values) for sub in fit_result["sub_models"]]
        return np.mean(preds, axis=0)

    ph_arr = ph_values.reshape(-1, 1)
    if fit_result.get("poly") is not None:
        ph_arr = fit_result["poly"].transform(ph_arr)

    if fit_result["type"] in ("knn", "ridge"):
        return fit_result["model"].predict(ph_arr)
    else:
        return fit_result["model"].predict(sm.add_constant(ph_arr, has_constant=False))


def predict_kwas(fit_result: dict, ph_start: float, masa_eff_ton: float,
                 feature: str = "ph_start") -> float:
    """Predict kwas_kg for a single observation."""
    if feature == "h3o_scaled":
        feat_val = 10.0 ** (12.0 - ph_start)
    else:
        feat_val = ph_start
    bc_pred = _predict_bc(fit_result, np.array([feat_val]))[0]
    target_delta = ph_start - TARGET_PH
    return bc_pred * target_delta * masa_eff_ton


def generate_plots(df: pd.DataFrame, fit_result: dict, cv_result: dict,
                   label: str, out_dir: str = "plots",
                   feature: str = "ph_start") -> list[str]:
    """Generate 5 diagnostic plots."""
    Path(out_dir).mkdir(exist_ok=True)
    paths = []
    actual_kg = df["kwas_kg"].values
    pred_kg = cv_result["predictions"]
    residuals_kg = cv_result["residuals"]
    masa_eff = df["masa_efektywna"].values
    feat_values = df[feature].values
    feat_label = "pH start" if feature == "ph_start" else "[H₃O⁺]·10¹² [mol/L]"

    # 1. Buffer capacity vs feature with fitted curve
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(feat_values, df["buffer_cap"], alpha=0.7, edgecolors="k", linewidths=0.5)
    feat_range = np.linspace(feat_values.min() - 0.05, feat_values.max() + 0.05, 200)
    bc_line = _predict_bc(fit_result, feat_range)
    ax.plot(feat_range, bc_line, "r-", linewidth=2)
    ax.set_xlabel(feat_label)
    ax.set_ylabel("Buffer capacity [kg/tonę/pH]")
    ax.set_title(f"{label}: zdolność buforowa vs {feat_label}")
    ax.grid(True, alpha=0.3)
    p = f"{out_dir}/{label}_buffer_cap_vs_ph.png"
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

    # 3. Residuals vs effective mass (normalization check)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(masa_eff, residuals_kg, alpha=0.7, edgecolors="k", linewidths=0.5)
    ax.axhline(0, color="r", linestyle="--", linewidth=1)
    ax.set_xlabel("Masa efektywna [kg]")
    ax.set_ylabel("Residuum [kg]")
    ax.set_title(f"{label}: residua vs masa efektywna")
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

    # 5. QQ-plot of residuals
    fig, ax = plt.subplots(figsize=(6, 6))
    stats.probplot(residuals_kg, dist="norm", plot=ax)
    ax.set_title(f"{label}: QQ-plot residuów")
    ax.grid(True, alpha=0.3)
    p = f"{out_dir}/{label}_qq_residuals.png"
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    paths.append(p)

    return paths


def main(out_dir: str = "plots_acid_estimation"):
    """Run full analysis: buffer capacity models comparison."""
    df = load_data("data/kwas.csv")
    df = add_features(df)
    print(f"Załadowano {len(df)} obserwacji z data/kwas.csv")
    print(f"Masy szarż: {sorted(df['masa_kg'].unique())}")
    print(f"Cel pH: {TARGET_PH}")
    print(f"\nStatystyki buffer capacity:")
    print(f"  mean  = {df['buffer_cap'].mean():.4f} kg/tonę/pH")
    print(f"  std   = {df['buffer_cap'].std():.4f}")
    print(f"  min   = {df['buffer_cap'].min():.4f}")
    print(f"  max   = {df['buffer_cap'].max():.4f}")

    # Define models to compare
    models = [
        # Regression models
        ("OLS linear",       {"model_type": "ols",   "degree": 1}),
        ("OLS poly deg=2",   {"model_type": "ols",   "degree": 2}),
        ("OLS poly deg=3",   {"model_type": "ols",   "degree": 3}),
        ("Ridge linear a=1", {"model_type": "ridge", "degree": 1, "alpha": 1.0}),
        ("Ridge poly2 a=1",  {"model_type": "ridge", "degree": 2, "alpha": 1.0}),
        ("Ridge poly2 a=10", {"model_type": "ridge", "degree": 2, "alpha": 10.0}),
        # KNN models
        ("KNN k=3",          {"model_type": "knn",   "degree": 1, "n_neighbors": 3}),
        ("KNN k=5",          {"model_type": "knn",   "degree": 1, "n_neighbors": 5}),
        ("KNN k=7",          {"model_type": "knn",   "degree": 1, "n_neighbors": 7}),
        # Ensemble: Ridge + KNN average
        ("Ens Ridge+KNN3",   {"ensemble": [
            {"model_type": "ridge", "degree": 1, "alpha": 1.0},
            {"model_type": "knn",   "degree": 1, "n_neighbors": 3},
        ]}),
        ("Ens Ridge+KNN5",   {"ensemble": [
            {"model_type": "ridge", "degree": 1, "alpha": 1.0},
            {"model_type": "knn",   "degree": 1, "n_neighbors": 5},
        ]}),
        ("Ens Rdg+OLS+KNN5", {"ensemble": [
            {"model_type": "ridge", "degree": 1, "alpha": 1.0},
            {"model_type": "ols",   "degree": 1},
            {"model_type": "knn",   "degree": 1, "n_neighbors": 5},
        ]}),
        ("Ens Rdg+Poly2+K5", {"ensemble": [
            {"model_type": "ridge", "degree": 1, "alpha": 1.0},
            {"model_type": "ols",   "degree": 2},
            {"model_type": "knn",   "degree": 1, "n_neighbors": 5},
        ]}),
        # KNN on polynomial features
        ("KNN k=5 poly2",    {"model_type": "knn",   "degree": 2, "n_neighbors": 5}),
        ("KNN k=7 poly2",    {"model_type": "knn",   "degree": 2, "n_neighbors": 7}),
        # Boosted: OLS poly2 base + KNN corrector on residuals
        ("Boost Poly2+KNN3", {"boosted": {
            "base": {"model_type": "ols", "degree": 2},
            "corrector": {"model_type": "knn", "degree": 1, "n_neighbors": 3},
        }}),
        ("Boost Poly2+KNN5", {"boosted": {
            "base": {"model_type": "ols", "degree": 2},
            "corrector": {"model_type": "knn", "degree": 1, "n_neighbors": 5},
        }}),
        ("Boost Poly2+KNN7", {"boosted": {
            "base": {"model_type": "ols", "degree": 2},
            "corrector": {"model_type": "knn", "degree": 1, "n_neighbors": 7},
        }}),
        # Stacking: OLS poly2 + KNN → Ridge meta
        ("Stack Poly2+K5",   {"stacked": {
            "base_models": [
                {"model_type": "ols", "degree": 2},
                {"model_type": "knn", "degree": 1, "n_neighbors": 5},
            ],
            "meta": {"alpha": 1.0},
        }}),
        ("Stack Poly2+K7",   {"stacked": {
            "base_models": [
                {"model_type": "ols", "degree": 2},
                {"model_type": "knn", "degree": 1, "n_neighbors": 7},
            ],
            "meta": {"alpha": 1.0},
        }}),
        ("Stack OLS+Poly2+K5", {"stacked": {
            "base_models": [
                {"model_type": "ols", "degree": 1},
                {"model_type": "ols", "degree": 2},
                {"model_type": "knn", "degree": 1, "n_neighbors": 5},
            ],
            "meta": {"alpha": 1.0},
        }}),
        # H3O+ scaled feature models
        ("H3O OLS linear",   {"model_type": "ols",   "degree": 1, "feature": "h3o_scaled"}),
        ("H3O OLS poly2",    {"model_type": "ols",   "degree": 2, "feature": "h3o_scaled"}),
        ("H3O Ridge lin",    {"model_type": "ridge", "degree": 1, "alpha": 1.0, "feature": "h3o_scaled"}),
        ("H3O Ridge poly2",  {"model_type": "ridge", "degree": 2, "alpha": 1.0, "feature": "h3o_scaled"}),
        ("H3O KNN k=5",      {"model_type": "knn",   "degree": 1, "n_neighbors": 5, "feature": "h3o_scaled"}),
        ("H3O KNN k=7",      {"model_type": "knn",   "degree": 1, "n_neighbors": 7, "feature": "h3o_scaled"}),
    ]

    results = []
    for name, params in models:
        cv = run_loocv(df, **params)
        fit = fit_full_model(df, **params)
        results.append((name, params, fit, cv))

    # Print comparison table
    print(f"\n{'='*70}")
    print(f"  Porównanie modeli (LOOCV)")
    print(f"{'='*70}")
    print(f"  {'Model':<22s}  {'MAE [kg]':>9s}  {'MAPE [%]':>9s}  {'R² CV':>8s}  {'R² train':>9s}")
    print(f"  {'-'*22}  {'-'*9}  {'-'*9}  {'-'*8}  {'-'*9}")

    best_mae = min(r[3]["mae_kg"] for r in results)
    best_idx = 0
    for i, (name, params, fit, cv) in enumerate(results):
        marker = " <--" if cv["mae_kg"] == best_mae else ""
        print(f"  {name:<22s}  {cv['mae_kg']:>9.2f}  {cv['mape_pct']:>9.1f}  {cv['r2_cv']:>8.4f}  {fit['r_squared']:>9.4f}{marker}")
        if cv["mae_kg"] == best_mae:
            best_idx = i

    best_name, best_params, best_fit, best_cv = results[best_idx]

    # OLS details for linear model
    ols_name, _, ols_fit, ols_cv = results[0]
    if ols_fit["type"] == "ols":
        print(f"\n{'='*70}")
        print(f"  Szczegóły: {ols_name}")
        print(f"{'='*70}")
        print(f"\n  buffer_cap = β₀ + β₁·pH_start")
        coefs = ols_fit["coefficients"]
        pvals = ols_fit["p_values"]
        labels = ["const", "pH_start"]
        for j, (c, p) in enumerate(zip(coefs, pvals)):
            sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
            print(f"  {labels[j]:>15s} = {c:>10.6f}  (p={p:.4f}) {sig}")

    # Winner summary
    print(f"\n{'='*70}")
    print(f"  Zwycięzca: {best_name}")
    print(f"{'='*70}")
    print(f"  MAE  = {best_cv['mae_kg']:.2f} kg")
    print(f"  MAPE = {best_cv['mape_pct']:.1f}%")
    print(f"  R²   = {best_cv['r2_cv']:.4f}")

    # Prediction examples
    best_feature = best_params.get("feature", "ph_start")
    print(f"\n{'='*70}")
    print(f"  Przykłady predykcji ({best_name}, cel pH={TARGET_PH})")
    print(f"{'='*70}")
    for masa, woda_refr in [(7400, 500), (8600, 600), (12600, 850)]:
        masa_eff_ton = (masa + woda_refr) / 1000.0
        for ph in [11.50, 11.70, 11.90]:
            kwas = predict_kwas(best_fit, ph, masa_eff_ton, feature=best_feature)
            print(f"  masa={masa}, woda_refr={woda_refr}, pH={ph:.2f} → kwas ≈ {kwas:.1f} kg")

    # Generate plots for best model only
    generate_plots(df, best_fit, best_cv, best_name.replace(" ", "_"), out_dir,
                   feature=best_feature)
    print(f"\nWykresy zapisane do {out_dir}/")


if __name__ == "__main__":
    main()
