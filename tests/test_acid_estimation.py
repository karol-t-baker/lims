import os
import shutil

import pandas as pd
import numpy as np
import pytest


def make_sample_df():
    """Minimal sample matching kwas.csv structure (5 rows for polynomial fits)."""
    return pd.DataFrame({
        "masa_kg": [12600, 8600, 7400, 12600, 8600],
        "kwas_kg": [100.0, 75.0, 63.0, 94.0, 69.0],
        "woda_kg": [915.0, 600.0, 530.0, 820.0, 600.0],
        "ph_start": [11.72, 11.77, 11.76, 11.57, 11.64],
        "ph_koniec": [6.2, 6.47, 6.04, 6.17, 6.20],
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

    # woda_refrakcja = woda_kg - kwas_kg
    expected_wr = [815.0, 525.0, 467.0, 726.0, 531.0]
    np.testing.assert_allclose(result["woda_refrakcja"].values, expected_wr, rtol=1e-6)

    # masa_efektywna = masa_kg + woda_refrakcja
    expected_me = [12600 + 815, 8600 + 525, 7400 + 467, 12600 + 726, 8600 + 531]
    np.testing.assert_allclose(result["masa_efektywna"].values, expected_me, rtol=1e-6)

    # kwas_per_eff_ton = kwas_kg / (masa_efektywna / 1000)
    for i in range(len(df)):
        expected = df["kwas_kg"].iloc[i] / (expected_me[i] / 1000.0)
        assert abs(result["kwas_per_eff_ton"].iloc[i] - expected) < 1e-6

    # delta_ph = ph_start - ph_koniec
    expected_dp = [11.72 - 6.2, 11.77 - 6.47, 11.76 - 6.04, 11.57 - 6.17, 11.64 - 6.20]
    np.testing.assert_allclose(result["delta_ph"].values, expected_dp, rtol=1e-6)

    # buffer_cap = kwas_per_eff_ton / delta_ph
    for i in range(len(df)):
        kpt = df["kwas_kg"].iloc[i] / (expected_me[i] / 1000.0)
        expected_bc = kpt / expected_dp[i]
        assert abs(result["buffer_cap"].iloc[i] - expected_bc) < 1e-6


def test_fit_full_model_ols():
    from acid_estimation_analysis import add_features, fit_full_model
    df = add_features(make_sample_df())
    result = fit_full_model(df, model_type="ols", degree=1)
    assert result["type"] == "ols"
    assert result["degree"] == 1
    assert "r_squared" in result
    assert "coefficients" in result
    assert len(result["coefficients"]) == 2  # const + pH_start


def test_fit_full_model_ridge_poly():
    from acid_estimation_analysis import add_features, fit_full_model
    df = add_features(make_sample_df())
    result = fit_full_model(df, model_type="ridge", degree=2, alpha=1.0)
    assert result["type"] == "ridge"
    assert result["degree"] == 2
    assert "r_squared" in result


def test_loocv_ols():
    from acid_estimation_analysis import load_data, add_features, run_loocv
    df = load_data("data/kwas.csv")
    df = add_features(df)
    metrics = run_loocv(df, model_type="ols", degree=1)
    assert 0 < metrics["mae_kg"] < 50
    assert 0 < metrics["mape_pct"] < 100
    assert len(metrics["residuals"]) == 45
    assert len(metrics["predictions"]) == 45


def test_loocv_ridge_poly():
    from acid_estimation_analysis import load_data, add_features, run_loocv
    df = load_data("data/kwas.csv")
    df = add_features(df)
    metrics = run_loocv(df, model_type="ridge", degree=2, alpha=1.0)
    assert 0 < metrics["mae_kg"] < 50
    assert len(metrics["predictions"]) == 45


def test_predict_kwas():
    from acid_estimation_analysis import load_data, add_features, fit_full_model, predict_kwas
    df = load_data("data/kwas.csv")
    df = add_features(df)
    fit = fit_full_model(df, model_type="ols", degree=1)
    kwas = predict_kwas(fit, ph_start=11.70, masa_eff_ton=13.5)
    assert 50 < kwas < 200  # sanity bounds


def test_generate_plots():
    from acid_estimation_analysis import load_data, add_features, fit_full_model, run_loocv, generate_plots
    df = load_data("data/kwas.csv")
    df = add_features(df)
    fit = fit_full_model(df, model_type="ols", degree=1)
    cv = run_loocv(df, model_type="ols", degree=1)

    out_dir = "test_plots_output"
    generate_plots(df, fit, cv, label="Test", out_dir=out_dir)

    expected_files = [
        f"{out_dir}/Test_buffer_cap_vs_ph.png",
        f"{out_dir}/Test_pred_vs_actual.png",
        f"{out_dir}/Test_residuals_vs_masa.png",
        f"{out_dir}/Test_residuals_vs_fitted.png",
        f"{out_dir}/Test_qq_residuals.png",
    ]
    for f in expected_files:
        assert os.path.exists(f), f"Missing plot: {f}"
    shutil.rmtree(out_dir)


def test_fit_knn():
    from acid_estimation_analysis import load_data, add_features, fit_full_model, predict_kwas
    df = load_data("data/kwas.csv")
    df = add_features(df)
    fit = fit_full_model(df, model_type="knn", degree=1, n_neighbors=5)
    assert fit["type"] == "knn"
    assert fit["n_neighbors"] == 5
    assert 0 < fit["r_squared"] <= 1.0
    kwas = predict_kwas(fit, ph_start=11.70, masa_eff_ton=13.5)
    assert 50 < kwas < 200


def test_loocv_knn():
    from acid_estimation_analysis import load_data, add_features, run_loocv
    df = load_data("data/kwas.csv")
    df = add_features(df)
    metrics = run_loocv(df, model_type="knn", degree=1, n_neighbors=5)
    assert 0 < metrics["mae_kg"] < 50
    assert len(metrics["predictions"]) == 45


def test_ensemble():
    from acid_estimation_analysis import load_data, add_features, fit_full_model, run_loocv, predict_kwas
    df = load_data("data/kwas.csv")
    df = add_features(df)
    ens_cfg = [
        {"model_type": "ridge", "degree": 1, "alpha": 1.0},
        {"model_type": "knn", "degree": 1, "n_neighbors": 5},
    ]
    fit = fit_full_model(df, ensemble=ens_cfg)
    assert fit["type"] == "ensemble"
    assert len(fit["sub_models"]) == 2
    kwas = predict_kwas(fit, ph_start=11.70, masa_eff_ton=13.5)
    assert 50 < kwas < 200

    cv = run_loocv(df, ensemble=ens_cfg)
    assert 0 < cv["mae_kg"] < 50
    assert len(cv["predictions"]) == 45


def test_main_report(capsys):
    from acid_estimation_analysis import main
    main(out_dir="test_report_output")
    captured = capsys.readouterr()
    assert "buffer capacity" in captured.out.lower() or "Buffer capacity" in captured.out or "buffer_cap" in captured.out
    assert "MAE" in captured.out
    assert "Zwycięzca" in captured.out or "zwyciezca" in captured.out.lower()
    if os.path.exists("test_report_output"):
        shutil.rmtree("test_report_output")
