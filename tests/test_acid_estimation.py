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
