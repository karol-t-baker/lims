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
from scipy.stats import spearmanr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.linear_model import ElasticNetCV, ElasticNet
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import LeaveOneOut
import base64
from io import BytesIO

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


def analyze_correlations(df: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    """Approach A: Spearman correlation with target + scatter plots."""
    figs = []

    meta_cols = ["batch_id", "produkt", "nr_partii", "template_id",
                 "nr_amidatora", "nr_mieszalnika", "acid_total_kg"]
    num_cols = [c for c in df.select_dtypes(include=[np.number]).columns
                if c not in meta_cols and c != "acid_kg_per_ton"]

    # Spearman correlation with target
    corr_results = []
    for col in num_cols:
        valid = df[[col, "acid_kg_per_ton"]].dropna()
        if len(valid) < 5:
            continue
        rho, pval = spearmanr(valid[col], valid["acid_kg_per_ton"])
        corr_results.append({
            "feature": col,
            "spearman_rho": round(rho, 3),
            "p_value": round(pval, 4),
            "n_valid": len(valid),
            "abs_rho": abs(rho),
        })

    corr_df = pd.DataFrame(corr_results).sort_values("abs_rho", ascending=False)
    print("\n=== Spearman correlations with acid_kg_per_ton ===")
    print(corr_df.to_string(index=False))

    # Heatmap of top features
    top_feats = corr_df.head(15)["feature"].tolist()
    if top_feats:
        corr_matrix = df[top_feats + ["acid_kg_per_ton"]].corr(method="spearman")
        fig, ax = plt.subplots(figsize=(12, 10))
        sns.heatmap(corr_matrix, annot=True, fmt=".2f", cmap="RdBu_r",
                    center=0, vmin=-1, vmax=1, ax=ax)
        ax.set_title("Spearman Correlation Matrix — Top 15 Features + Target")
        plt.tight_layout()
        figs.append(("corr_heatmap", fig))

    # Scatter plots: top 10 features vs target
    top10 = corr_df.head(10)["feature"].tolist()
    if top10:
        n_plots = len(top10)
        n_cols_plot = 2
        n_rows_plot = (n_plots + 1) // 2
        fig, axes = plt.subplots(n_rows_plot, n_cols_plot, figsize=(14, 4 * n_rows_plot))
        axes = axes.flatten()

        colors = {"Chegina K7": "#1f77b4", "Chegina K40GL": "#ff7f0e",
                  "Chegina K40GLO": "#2ca02c", "Chegina K40GLOL": "#d62728"}

        for i, feat in enumerate(top10):
            ax = axes[i]
            for prod, color in colors.items():
                mask = df["produkt"] == prod
                ax.scatter(df.loc[mask, feat], df.loc[mask, "acid_kg_per_ton"],
                          c=color, label=prod, s=60, alpha=0.8, edgecolors="k", linewidth=0.5)
            rho = corr_df[corr_df["feature"] == feat]["spearman_rho"].iloc[0]
            ax.set_xlabel(feat, fontsize=9)
            ax.set_ylabel("acid_kg_per_ton")
            ax.set_title(f"rho={rho:.3f}", fontsize=10)
            ax.grid(True, alpha=0.3)

        axes[0].legend(fontsize=7, loc="best")
        for j in range(len(top10), len(axes)):
            axes[j].set_visible(False)

        fig.suptitle("Top 10 Features vs Citric Acid Dosage (kg/ton)", fontsize=14, y=1.01)
        plt.tight_layout()
        figs.append(("scatter_top10", fig))

    return corr_df, figs


def analyze_elasticnet(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list]:
    """Approach B: ElasticNet with LOO-CV + bootstrap stability."""
    figs = []

    meta_cols = ["batch_id", "produkt", "nr_partii", "template_id",
                 "nr_amidatora", "nr_mieszalnika", "acid_total_kg"]
    num_cols = [c for c in df.select_dtypes(include=[np.number]).columns
                if c not in meta_cols and c != "acid_kg_per_ton"]

    # Prepare X, y — drop rows/cols with NaN
    sub = df[num_cols + ["acid_kg_per_ton"]].dropna(axis=1, thresh=int(len(df) * 0.6))
    sub = sub.dropna()
    feat_cols = [c for c in sub.columns if c != "acid_kg_per_ton"]

    X = sub[feat_cols].values
    y = sub["acid_kg_per_ton"].values
    print(f"\nElasticNet: {X.shape[0]} samples, {X.shape[1]} features")
    print(f"Features used: {feat_cols}")

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # LOO-CV ElasticNet
    alphas = np.logspace(-3, 1, 20)
    l1_ratios = [0.1, 0.3, 0.5, 0.7, 0.9, 1.0]

    enet_cv = ElasticNetCV(
        l1_ratio=l1_ratios, alphas=alphas,
        cv=LeaveOneOut(), max_iter=10000,
        random_state=42
    )
    enet_cv.fit(X_scaled, y)
    print(f"Best alpha={enet_cv.alpha_:.4f}, l1_ratio={enet_cv.l1_ratio_:.2f}")
    print(f"LOO R²={enet_cv.score(X_scaled, y):.3f}")

    # Coefficients
    coef_df = pd.DataFrame({
        "feature": feat_cols,
        "coefficient": enet_cv.coef_,
        "abs_coef": np.abs(enet_cv.coef_),
    }).sort_values("abs_coef", ascending=False)
    print("\n=== ElasticNet coefficients ===")
    print(coef_df.to_string(index=False))

    # Bootstrap stability (100 iterations)
    n_boot = 100
    boot_selected = {f: 0 for f in feat_cols}
    boot_coefs = {f: [] for f in feat_cols}
    rng = np.random.RandomState(42)

    for _ in range(n_boot):
        idx = rng.choice(len(X_scaled), size=len(X_scaled), replace=True)
        X_b, y_b = X_scaled[idx], y[idx]
        enet = ElasticNet(alpha=enet_cv.alpha_, l1_ratio=enet_cv.l1_ratio_, max_iter=10000)
        enet.fit(X_b, y_b)
        for j, f in enumerate(feat_cols):
            if abs(enet.coef_[j]) > 1e-6:
                boot_selected[f] += 1
            boot_coefs[f].append(enet.coef_[j])

    stability_df = pd.DataFrame({
        "feature": feat_cols,
        "selection_pct": [boot_selected[f] / n_boot * 100 for f in feat_cols],
        "coef_mean": [np.mean(boot_coefs[f]) for f in feat_cols],
        "coef_std": [np.std(boot_coefs[f]) for f in feat_cols],
    }).sort_values("selection_pct", ascending=False)
    print("\n=== Bootstrap stability (100 iterations) ===")
    print(stability_df.to_string(index=False))

    # Stability bar chart
    fig, ax = plt.subplots(figsize=(12, 6))
    top_stab = stability_df.head(20)
    bars = ax.barh(range(len(top_stab)), top_stab["selection_pct"],
                   color=["#2196F3" if p >= 80 else "#FFC107" if p >= 50 else "#E0E0E0"
                          for p in top_stab["selection_pct"]])
    ax.set_yticks(range(len(top_stab)))
    ax.set_yticklabels(top_stab["feature"], fontsize=9)
    ax.set_xlabel("Bootstrap Selection Frequency (%)")
    ax.set_title("ElasticNet Bootstrap Stability — Feature Selection Frequency")
    ax.axvline(x=80, color="red", linestyle="--", alpha=0.5, label="80% threshold")
    ax.axvline(x=50, color="orange", linestyle="--", alpha=0.5, label="50% threshold")
    ax.legend()
    ax.invert_yaxis()
    plt.tight_layout()
    figs.append(("bootstrap_stability", fig))

    return stability_df, coef_df, figs


def build_combined_ranking(corr_df: pd.DataFrame, stability_df: pd.DataFrame) -> pd.DataFrame:
    """Combine Approach A (correlation) and B (ElasticNet stability) into final ranking."""

    merged = corr_df[["feature", "spearman_rho", "abs_rho", "p_value"]].merge(
        stability_df[["feature", "selection_pct", "coef_mean"]],
        on="feature", how="outer"
    )

    if merged["abs_rho"].max() > 0:
        merged["corr_score"] = merged["abs_rho"] / merged["abs_rho"].max()
    else:
        merged["corr_score"] = 0

    if merged["selection_pct"].max() > 0:
        merged["stability_score"] = merged["selection_pct"] / merged["selection_pct"].max()
    else:
        merged["stability_score"] = 0

    merged["combined_score"] = (
        0.5 * merged["corr_score"].fillna(0) +
        0.5 * merged["stability_score"].fillna(0)
    )

    domain_notes = {
        "last_ph_10proc": "Direct: higher pH = more acid to neutralize",
        "naoh_czwart_kg_per_ton": "Direct: more NaOH used = more alkaline = more acid",
        "wielkosc_kg": "Scale effect: larger batches may have different proportions",
        "delta_ph_czwart": "pH change during quaternization reflects NaOH absorption",
        "last_procent_aa": "Active amines residual — may affect acid demand",
        "last_nd20": "Refractive index — product composition indicator",
        "dmapa_total_kg_per_ton": "DMAPA amount affects amine content → pH",
        "mca_80_kg_per_ton": "MCA amount affects quaternization completeness",
        "lk_amid_last": "Acid number after amidation — residual acidity",
        "ph_smca": "SMCA pH — affects downstream chemistry",
        "czas_czwart_h": "Longer quaternization may indicate process difficulties",
        "n_analiz_czwart": "More analyses = more complex process trajectory",
    }
    merged["domain_note"] = merged["feature"].map(domain_notes).fillna("")

    merged = merged.sort_values("combined_score", ascending=False)
    return merged


def fig_to_base64(fig) -> str:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def generate_html_report(
    df: pd.DataFrame,
    ranking: pd.DataFrame,
    corr_df: pd.DataFrame,
    stability_df: pd.DataFrame,
    all_figs: list,
):
    """Generate self-contained HTML report."""

    fig_html = ""
    for name, fig in all_figs:
        b64 = fig_to_base64(fig)
        fig_html += f'<div class="chart"><img src="data:image/png;base64,{b64}" alt="{name}"></div>\n'

    ranking_html = ranking.round(3).to_html(index=False, classes="table")
    corr_html = corr_df.round(3).to_html(index=False, classes="table")
    stability_html = stability_df.round(3).to_html(index=False, classes="table")

    n_batches = len(df)
    n_features = len(ranking)
    target_stats = df["acid_kg_per_ton"].describe()

    recommended_html = ""
    for _, row in ranking.head(8).iterrows():
        note = f" — <em>{row['domain_note']}</em>" if row.get("domain_note") else ""
        recommended_html += f"<li><strong>{row['feature']}</strong> (score: {row['combined_score']:.2f}){note}</li>\n"

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<title>Feature Selection Report — Citric Acid Dosage</title>
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
    .recommended {{ background: #e8f5e9; border-left: 4px solid #4caf50;
                    padding: 15px 20px; margin: 20px 0; border-radius: 0 8px 8px 0; }}
    .table {{ border-collapse: collapse; width: 100%; margin: 15px 0; font-size: 13px; }}
    .table th {{ background: #283593; color: white; padding: 8px 12px; text-align: left; }}
    .table td {{ padding: 6px 12px; border-bottom: 1px solid #e0e0e0; }}
    .table tr:hover {{ background: #e3f2fd; }}
    .chart {{ background: white; border-radius: 8px; padding: 15px; margin: 20px 0;
              box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center; }}
    .chart img {{ max-width: 100%; height: auto; }}
    .note {{ background: #fff3e0; border-left: 4px solid #ff9800;
             padding: 10px 15px; margin: 10px 0; font-size: 13px; }}
</style>
</head>
<body>

<h1>Feature Selection Report — Citric Acid Dosage Prediction</h1>
<p>Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="summary">
    <div class="stat"><div class="value">{n_batches}</div><div class="label">Batches</div></div>
    <div class="stat"><div class="value">{n_features}</div><div class="label">Features analyzed</div></div>
    <div class="stat"><div class="value">{target_stats['mean']:.1f}</div><div class="label">Mean acid (kg/t)</div></div>
    <div class="stat"><div class="value">{target_stats['min']:.1f}–{target_stats['max']:.1f}</div><div class="label">Range (kg/t)</div></div>
    <div class="stat"><div class="value">{target_stats['std']:.1f}</div><div class="label">Std dev (kg/t)</div></div>
</div>

<div class="note">
    <strong>Caveat:</strong> n={n_batches} is very small. All results are exploratory, not confirmatory.
    Feature rankings should be validated as more batches are collected.
</div>

<h2>Recommended Feature Set</h2>
<div class="recommended">
    <p><strong>Top features (combined Spearman + ElasticNet stability):</strong></p>
    <ul>
{recommended_html}
    </ul>
</div>

<h2>Visualizations</h2>
{fig_html}

<h2>Approach A — Spearman Rank Correlation</h2>
<p>Spearman correlation is robust at small n and captures monotonic (not just linear) relationships.</p>
{corr_html}

<h2>Approach B — ElasticNet Bootstrap Stability</h2>
<p>ElasticNet with LOO-CV + 100 bootstrap resamples. Features selected &gt;80% are highly stable.</p>
{stability_html}

<h2>Combined Ranking</h2>
<p>50% Spearman |rho| (normalized) + 50% bootstrap selection frequency (normalized).</p>
{ranking_html}

</body>
</html>"""

    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"\nHTML report saved: {OUT_HTML}")


if __name__ == "__main__":
    db = get_db()

    print("=" * 60)
    print("Feature Selection Analysis — Citric Acid Dosage")
    print("=" * 60)

    print("\n[1/6] Building target variable...")
    df = build_target(db)

    print("[2/6] Extracting raw material features...")
    df = build_raw_material_features(db, df)

    print("[3/6] Extracting process analysis features...")
    df = build_analysis_features(db, df)

    print("[4/6] Extracting timing features...")
    df = build_timing_features(db, df)

    print("[5/6] Extracting sensor features...")
    df = build_sensor_features(db, df)

    print("[6/6] Cleaning and exporting...")
    df = clean_and_export(df)

    print("\n" + "=" * 60)
    print("Running Approach A: Spearman Correlation")
    print("=" * 60)
    corr_df, figs_a = analyze_correlations(df)

    print("\n" + "=" * 60)
    print("Running Approach B: ElasticNet + Bootstrap")
    print("=" * 60)
    stability_df, coef_df, figs_b = analyze_elasticnet(df)

    print("\n" + "=" * 60)
    print("Building combined ranking + HTML report")
    print("=" * 60)
    ranking = build_combined_ranking(corr_df, stability_df)
    all_figs = figs_a + figs_b
    generate_html_report(df, ranking, corr_df, stability_df, all_figs)

    print("\n=== RECOMMENDED FEATURES ===")
    for _, row in ranking.head(8).iterrows():
        note = f"  ({row['domain_note']})" if row.get("domain_note") else ""
        print(f"  {row['combined_score']:.2f}  {row['feature']}{note}")

    print(f"\nDone! Open {OUT_HTML} in browser.")

    db.close()
