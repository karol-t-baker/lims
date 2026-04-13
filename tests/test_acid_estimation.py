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


def test_fit_model_a():
    from acid_estimation_analysis import add_features, fit_model
    df = add_features(make_sample_df())
    result = fit_model(df, predictors=["ph_start"])
    assert "coefficients" in result
    assert "r_squared" in result
    assert "p_values" in result
    assert "model" in result
    assert len(result["coefficients"]) == 2  # const + ph_start


def test_fit_model_b():
    from acid_estimation_analysis import add_features, fit_model
    df = add_features(make_sample_df())
    result = fit_model(df, predictors=["ph_start", "woda_refrakcja_per_ton"])
    assert len(result["coefficients"]) == 3  # const + 2 predictors


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
