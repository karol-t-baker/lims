"""
feature_analysis.py — Feature selection for citric acid dosage prediction.

Reads from data/batch_db.sqlite, builds feature table, runs correlation +
ElasticNet analysis, outputs CSV + HTML report.

Usage:
    python feature_analysis.py
"""

import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

DB_PATH = Path("data/batch_db.sqlite")
OUT_CSV = Path("data/parquet/feature_table.csv")
OUT_HTML = Path("raport_feature_selection.html")


def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


def build_target(db: sqlite3.Connection) -> pd.DataFrame:
    """Build target: total citric acid kg/ton per batch."""
    df = pd.read_sql("""
        SELECT
            b.batch_id,
            b.produkt,
            b.nr_partii,
            b.wielkosc_kg,
            b.nr_amidatora,
            b.nr_mieszalnika,
            b.template_id,
            COALESCE(acid.total_kg, 0) as acid_total_kg
        FROM batches b
        LEFT JOIN (
            SELECT batch_id, SUM(ilosc_kg) as total_kg
            FROM standardization
            WHERE kod_dodatku = 'kw_cytrynowy'
            GROUP BY batch_id
        ) acid ON b.batch_id = acid.batch_id
    """, db)
    df["acid_kg_per_ton"] = df["acid_total_kg"] / (df["wielkosc_kg"] / 1000)
    return df


def build_raw_material_features(db: sqlite3.Connection, df: pd.DataFrame) -> pd.DataFrame:
    """Extract normalized raw material quantities per ton."""
    rm = pd.read_sql("""
        SELECT batch_id, kod_surowca,
               COALESCE(ilosc_zalad_kg, ilosc_recept_kg) as kg,
               ilosc_recept_kg, ilosc_zalad_kg
        FROM raw_materials
    """, db)

    ton = df.set_index("batch_id")["wielkosc_kg"] / 1000

    # Pivot key raw materials per ton
    for kod in ["kwasy_c1218", "cno", "pko", "dmapa_czysta", "dmapa_zwrotna", "mca_80", "naoh_50", "na2so3", "gliceryna"]:
        sub = rm[rm["kod_surowca"] == kod].groupby("batch_id")["kg"].sum()
        col = f"{kod}_kg_per_ton"
        df[col] = df["batch_id"].map(sub) / df["batch_id"].map(ton)

    # DMAPA total (czysta + zwrotna)
    dmapa = rm[rm["kod_surowca"].isin(["dmapa_czysta", "dmapa_zwrotna"])].groupby("batch_id")["kg"].sum()
    df["dmapa_total_kg_per_ton"] = df["batch_id"].map(dmapa) / df["batch_id"].map(ton)

    # Max absolute recipe deviation %
    rm["delta_pct"] = ((rm["ilosc_zalad_kg"] - rm["ilosc_recept_kg"]) / rm["ilosc_recept_kg"] * 100).abs()
    max_delta = rm.groupby("batch_id")["delta_pct"].max()
    df["max_delta_surowce_pct"] = df["batch_id"].map(max_delta)

    return df


def build_analysis_features(db: sqlite3.Connection, df: pd.DataFrame) -> pd.DataFrame:
    """Extract last-known analysis values before standardization."""

    for _, row in df.iterrows():
        bid = row["batch_id"]

        # Last czwartorzedowanie analysis (highest id = latest)
        last_czwart = pd.read_sql("""
            SELECT ph_10proc, nd20, procent_aa, procent_so3, barwa_hz, barwa_fau
            FROM analyses
            WHERE batch_id = ? AND etap = 'czwartorzedowanie' AND source = 'proces_kroki'
            ORDER BY id DESC LIMIT 1
        """, db, params=(bid,))
        if not last_czwart.empty:
            for col in last_czwart.columns:
                df.loc[df["batch_id"] == bid, f"last_{col}"] = last_czwart[col].iloc[0]

        # Second-to-last czwart pH (to get pH before last NaOH addition)
        prev_czwart = pd.read_sql("""
            SELECT ph_10proc
            FROM analyses
            WHERE batch_id = ? AND etap = 'czwartorzedowanie' AND source = 'proces_kroki'
            AND ph_10proc IS NOT NULL
            ORDER BY id DESC LIMIT 1 OFFSET 1
        """, db, params=(bid,))
        if not prev_czwart.empty:
            df.loc[df["batch_id"] == bid, "prev_ph_10proc"] = prev_czwart["ph_10proc"].iloc[0]

        # pH delta (how much pH changed during czwartorzedowanie)
        first_czwart = pd.read_sql("""
            SELECT ph_10proc
            FROM analyses
            WHERE batch_id = ? AND etap = 'czwartorzedowanie' AND source = 'proces_kroki'
            AND ph_10proc IS NOT NULL
            ORDER BY id ASC LIMIT 1
        """, db, params=(bid,))
        if not first_czwart.empty and not last_czwart.empty:
            first_ph = first_czwart["ph_10proc"].iloc[0]
            last_ph = last_czwart["ph_10proc"].iloc[0]
            if first_ph is not None and last_ph is not None:
                df.loc[df["batch_id"] == bid, "delta_ph_czwart"] = last_ph - first_ph

        # SMCA pH
        smca = pd.read_sql("""
            SELECT ph FROM analyses
            WHERE batch_id = ? AND etap = 'smca'
            ORDER BY id DESC LIMIT 1
        """, db, params=(bid,))
        if not smca.empty:
            df.loc[df["batch_id"] == bid, "ph_smca"] = smca["ph"].iloc[0]

        # Last amid acid number
        amid = pd.read_sql("""
            SELECT lk FROM analyses
            WHERE batch_id = ? AND etap = 'amid' AND lk IS NOT NULL
            ORDER BY id DESC LIMIT 1
        """, db, params=(bid,))
        if not amid.empty:
            df.loc[df["batch_id"] == bid, "lk_amid_last"] = amid["lk"].iloc[0]

        # Count of czwartorzedowanie analyses
        n_anal = pd.read_sql("""
            SELECT COUNT(*) as cnt FROM analyses
            WHERE batch_id = ? AND etap = 'czwartorzedowanie'
        """, db, params=(bid,))
        df.loc[df["batch_id"] == bid, "n_analiz_czwart"] = n_anal["cnt"].iloc[0]

    # Total NaOH from czwartorzedowanie (per ton)
    naoh = pd.read_sql("""
        SELECT batch_id, SUM(ilosc_kg) as naoh_kg
        FROM stages
        WHERE (substancja LIKE '%NaOH%' OR substancja LIKE '%naoh%')
        AND etap = 'czwartorzedowanie'
        GROUP BY batch_id
    """, db)
    naoh_map = naoh.set_index("batch_id")["naoh_kg"]
    ton = df.set_index("batch_id")["wielkosc_kg"] / 1000
    df["naoh_czwart_kg_per_ton"] = df["batch_id"].map(naoh_map) / df["batch_id"].map(ton)

    return df


def build_timing_features(db: sqlite3.Connection, df: pd.DataFrame) -> pd.DataFrame:
    """Extract process duration and step count features."""

    for _, row in df.iterrows():
        bid = row["batch_id"]

        # Amidation duration
        amid_times = pd.read_sql("""
            SELECT datetime_start, datetime_end FROM stages
            WHERE batch_id = ? AND etap = 'amid' AND sub_etap = 'reakcja_amidowania'
        """, db, params=(bid,))
        if not amid_times.empty and amid_times["datetime_start"].iloc[0] and amid_times["datetime_end"].iloc[0]:
            t0 = pd.to_datetime(amid_times["datetime_start"].iloc[0])
            t1 = pd.to_datetime(amid_times["datetime_end"].iloc[0])
            df.loc[df["batch_id"] == bid, "czas_amidowania_h"] = (t1 - t0).total_seconds() / 3600

        # Quaternization duration (first event to last event)
        czwart_span = pd.read_sql("""
            SELECT MIN(datetime_start) as t0, MAX(COALESCE(datetime_end, datetime_start)) as t1
            FROM stages
            WHERE batch_id = ? AND etap = 'czwartorzedowanie' AND datetime_start IS NOT NULL
        """, db, params=(bid,))
        if not czwart_span.empty and czwart_span["t0"].iloc[0] and czwart_span["t1"].iloc[0]:
            t0 = pd.to_datetime(czwart_span["t0"].iloc[0])
            t1 = pd.to_datetime(czwart_span["t1"].iloc[0])
            df.loc[df["batch_id"] == bid, "czas_czwart_h"] = (t1 - t0).total_seconds() / 3600

        # Total time: first stage to last analysis before standardization
        total_span = pd.read_sql("""
            SELECT MIN(s.datetime_start) as t0
            FROM stages s WHERE s.batch_id = ? AND s.datetime_start IS NOT NULL
        """, db, params=(bid,))
        last_anal = pd.read_sql("""
            SELECT MAX(datetime) as t1 FROM analyses
            WHERE batch_id = ? AND etap = 'czwartorzedowanie'
        """, db, params=(bid,))
        if (not total_span.empty and total_span["t0"].iloc[0] and
                not last_anal.empty and last_anal["t1"].iloc[0]):
            t0 = pd.to_datetime(total_span["t0"].iloc[0])
            t1 = pd.to_datetime(last_anal["t1"].iloc[0])
            df.loc[df["batch_id"] == bid, "czas_total_h"] = (t1 - t0).total_seconds() / 3600

        # Number of DMAPA corrections during amidation
        n_korekt = pd.read_sql("""
            SELECT COUNT(*) as cnt FROM stages
            WHERE batch_id = ? AND etap = 'amid' AND sub_etap = 'korekta'
            AND (substancja LIKE '%DMAPA%' OR substancja LIKE '%dmapa%')
        """, db, params=(bid,))
        df.loc[df["batch_id"] == bid, "n_korekt_dmapa"] = n_korekt["cnt"].iloc[0]

    return df


def build_sensor_features(db: sqlite3.Connection, df: pd.DataFrame) -> pd.DataFrame:
    """Extract sensor aggregates per stage (up to standardization)."""

    for _, row in df.iterrows():
        bid = row["batch_id"]

        # Reactor sensors by stage
        for etap in ["amid", "czwartorzedowanie"]:
            prefix = etap[:5]  # "amid" or "czwar"
            sensor = pd.read_sql("""
                SELECT temp_c, temp_plaszcz_c, proznia_bar
                FROM sensor_readings
                WHERE batch_id = ? AND source = 'reactor' AND etap = ?
            """, db, params=(bid, etap))

            if sensor.empty or sensor["temp_c"].isna().all():
                continue

            temp = sensor["temp_c"].dropna()
            if len(temp) > 0:
                df.loc[df["batch_id"] == bid, f"temp_reactor_mean_{prefix}"] = temp.mean()
                df.loc[df["batch_id"] == bid, f"temp_reactor_max_{prefix}"] = temp.max()
                df.loc[df["batch_id"] == bid, f"temp_reactor_std_{prefix}"] = temp.std()

                # Linear trend (slope per hour)
                if len(temp) > 10:
                    x = np.arange(len(temp), dtype=float)
                    slope = np.polyfit(x, temp.values, 1)[0]
                    # Convert to per-hour (readings ~every 3 min)
                    readings_per_hour = len(temp) / max((len(temp) * 3 / 60), 1)
                    df.loc[df["batch_id"] == bid, f"temp_reactor_trend_{prefix}"] = slope * readings_per_hour

            vac = sensor["proznia_bar"].dropna()
            if len(vac) > 0:
                df.loc[df["batch_id"] == bid, f"proznia_mean_{prefix}"] = vac.mean()
                df.loc[df["batch_id"] == bid, f"proznia_min_{prefix}"] = vac.min()

        # Mixer sensors during czwartorzedowanie
        mixer = pd.read_sql("""
            SELECT temp_c, dozownik_l
            FROM sensor_readings
            WHERE batch_id = ? AND source = 'mixer' AND etap = 'czwartorzedowanie'
        """, db, params=(bid,))

        if not mixer.empty:
            mt = mixer["temp_c"].dropna()
            if len(mt) > 0:
                df.loc[df["batch_id"] == bid, "temp_mixer_mean_czwar"] = mt.mean()
                df.loc[df["batch_id"] == bid, "temp_mixer_max_czwar"] = mt.max()

            doz = mixer["dozownik_l"].dropna()
            if len(doz) > 0 and doz.max() > 0:
                df.loc[df["batch_id"] == bid, "dozownik_total_czwar"] = doz.max() - doz.min()

    return df


def clean_and_export(df: pd.DataFrame) -> pd.DataFrame:
    """Clean feature table: report NaN, drop sparse columns, export CSV."""

    # Identify numeric feature columns (exclude metadata)
    meta_cols = ["batch_id", "produkt", "nr_partii", "template_id",
                 "nr_amidatora", "nr_mieszalnika", "acid_total_kg"]
    feature_cols = [c for c in df.columns if c not in meta_cols]

    # NaN report
    print("\n=== Missing values ===")
    nan_pct = df[feature_cols].isna().mean().sort_values(ascending=False)
    for col, pct in nan_pct.items():
        if pct > 0:
            print(f"  {col}: {pct:.0%} missing ({df[col].isna().sum()}/{len(df)})")

    # Drop columns with >50% NaN
    drop_cols = nan_pct[nan_pct > 0.5].index.tolist()
    if drop_cols:
        print(f"\nDropping {len(drop_cols)} columns with >50% NaN: {drop_cols}")
        df = df.drop(columns=drop_cols)

    # Export
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"\nFeature table saved: {OUT_CSV} ({len(df)} rows, {len(df.columns)} cols)")

    return df


if __name__ == "__main__":
    db = get_db()

    print("Building feature table...")
    df = build_target(db)
    df = build_raw_material_features(db, df)
    df = build_analysis_features(db, df)
    df = build_timing_features(db, df)
    df = build_sensor_features(db, df)
    df = clean_and_export(df)

    print(f"\nFinal shape: {df.shape}")
    print(df.describe().round(3).to_string())
