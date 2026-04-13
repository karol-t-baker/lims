"""
Acid estimation model for K7 chegina.

Compares two OLS models for predicting citric acid dosage (kg)
from batch mass and pH_start, with optional woda_refrakcja feature.

Usage:
    python acid_estimation_analysis.py
"""

import numpy as np
import pandas as pd


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
    """Add per-ton normalized features."""
    df = df.copy()
    tons = df["masa_kg"] / 1000.0
    df["kwas_per_ton"] = df["kwas_kg"] / tons
    df["woda_refrakcja"] = df["woda_kg"] - df["kwas_kg"]
    df["woda_refrakcja_per_ton"] = df["woda_refrakcja"] / tons
    return df
