"""Buffer-capacity diagnostic for the K7 acid model.

Computes actual vs. predicted buffer capacity for completed K7 batches and
generates a 3-subplot diagnostic PNG (time series, scatter, histogram).

Actual buffer_cap:  acid_kg / (masa_kg / 1000) / delta_ph
Predicted:          _acid_model_predict(masa_eff_kg, delta_ph, ph_start, masa_kg)

Port of the JS formula from mbr/templates/laborant/_correction_panel.html:446:
  result = -524.86 + 0.010864*masaEffKg + 9.2878*deltaPh + 33.218*phStart + 488181/masaKg
"""
import base64
import io
import math
import sqlite3
from typing import Any


# ── Model formula (ported from JS) ───────────────────────────────────────────

def _acid_model_predict(masa_eff_kg: float, delta_ph: float,
                        ph_start: float, masa_kg: float) -> float:
    """Predict acid buffer capacity (kg/t/ΔpH) using the OLS poly2 model."""
    return (-524.86
            + 0.010864 * masa_eff_kg
            + 9.2878 * delta_ph
            + 33.218 * ph_start
            + 488181.0 / masa_kg)


def _meff(masa_kg: float) -> float:
    return masa_kg - 1000.0 if masa_kg > 6600.0 else masa_kg - 500.0


# ── Data extraction ───────────────────────────────────────────────────────────

def _load_acid_rows(db: sqlite3.Connection, produkt: str) -> list[dict[str, Any]]:
    """Return rows suitable for buffer-cap computation from completed K7 batches.

    Joins ebr_batches → standaryzacja sessions → ph measurements + Kwas cytrynowy corrections.
    Returns list of dicts with keys: dt_start, masa_kg, ph_before, ph_after, acid_kg.
    """
    rows = db.execute(
        """
        SELECT b.ebr_id, b.dt_start, b.wielkosc_szarzy_kg AS masa_kg,
               ph_meas.wartosc AS ph_before,
               acid.ilosc      AS acid_kg
          FROM ebr_batches b
          JOIN mbr_templates mt ON mt.mbr_id = b.mbr_id
          JOIN ebr_etap_sesja s ON s.ebr_id = b.ebr_id
          JOIN etapy_analityczne ea ON ea.id = s.etap_id AND ea.kod = 'standaryzacja'
          -- ph measurement (parametr_id=1 = ph_10proc)
          JOIN ebr_pomiar ph_meas ON ph_meas.sesja_id = s.id
          JOIN parametry_analityczne pa ON pa.id = ph_meas.parametr_id AND pa.kod = 'ph_10proc'
          -- Kwas cytrynowy correction on the same session
          JOIN ebr_korekta_v2 acid ON acid.sesja_id = s.id
          JOIN etap_korekty_katalog ek ON ek.id = acid.korekta_typ_id
                                      AND ek.substancja = 'Kwas cytrynowy'
         WHERE mt.produkt = ?
           AND b.status = 'completed'
           AND b.typ = 'szarza'
         ORDER BY b.dt_start
        """,
        (produkt,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Stats computation ─────────────────────────────────────────────────────────

def _compute_rows(raw: list[dict], target_ph: float = 6.25) -> list[dict]:
    """Convert raw DB rows to (actual, predicted, dt_start) triples.

    Filters: delta_ph > 0.5, acid_kg > 0, ph_before >= 9.
    delta_ph is approximated as ph_before - target_ph (we use the global target).
    """
    out = []
    for r in raw:
        masa_kg = r.get("masa_kg") or 0.0
        ph_before = r.get("ph_before") or 0.0
        acid_kg = r.get("acid_kg") or 0.0
        if masa_kg <= 0 or acid_kg <= 0:
            continue
        delta_ph = ph_before - target_ph
        if delta_ph <= 0.5 or ph_before < 9.0:
            continue
        tons = masa_kg / 1000.0
        actual = acid_kg / tons / delta_ph
        predicted = _acid_model_predict(_meff(masa_kg), delta_ph, ph_before, masa_kg)
        out.append({
            "dt_start": r.get("dt_start", ""),
            "actual": actual,
            "predicted": predicted,
            "residual": predicted - actual,
        })
    return out


def compute_buffer_cap_stats(db: sqlite3.Connection,
                             produkt: str = "Chegina_K7") -> dict[str, Any]:
    """Return summary stats dict: {n, mae, mape, mean_bias, stdev}."""
    raw = _load_acid_rows(db, produkt)
    rows = _compute_rows(raw)
    n = len(rows)
    if n == 0:
        return {"n": 0, "mae": 0.0, "mape": 0.0, "mean_bias": 0.0, "stdev": 0.0}
    residuals = [r["residual"] for r in rows]
    actuals = [r["actual"] for r in rows]
    mae = sum(abs(e) for e in residuals) / n
    mape = 100.0 * sum(abs(e / a) for e, a in zip(residuals, actuals) if a != 0) / n
    mean_bias = sum(residuals) / n
    stdev = math.sqrt(sum((e - mean_bias) ** 2 for e in residuals) / n) if n > 1 else 0.0
    return {
        "n": n,
        "mae": round(mae, 4),
        "mape": round(mape, 2),
        "mean_bias": round(mean_bias, 4),
        "stdev": round(stdev, 4),
    }


# ── Chart generation ──────────────────────────────────────────────────────────

def generate_chart_png(db: sqlite3.Connection,
                       produkt: str = "Chegina_K7") -> tuple[dict, bytes]:
    """Generate 3-subplot diagnostic PNG + stats dict.

    Returns (stats_dict, png_bytes).
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        # Return a 1x1 transparent PNG placeholder if matplotlib unavailable.
        _EMPTY_PNG = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00'
            b'\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        return compute_buffer_cap_stats(db, produkt), _EMPTY_PNG

    raw = _load_acid_rows(db, produkt)
    rows = _compute_rows(raw)
    stats = compute_buffer_cap_stats(db, produkt)

    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    fig.suptitle(
        f"K7 Buffer Capacity Diagnostics  |  n={stats['n']}  "
        f"MAE={stats['mae']:.3f}  MAPE={stats['mape']:.1f}%  "
        f"bias={stats['mean_bias']:+.3f}  σ={stats['stdev']:.3f}",
        fontsize=10,
    )

    if rows:
        xs = list(range(len(rows)))
        actuals   = [r["actual"]    for r in rows]
        predicted = [r["predicted"] for r in rows]
        residuals = [r["residual"]  for r in rows]
        labels    = [r["dt_start"][:10] for r in rows]

        # 1. Time series
        ax = axes[0]
        ax.plot(xs, actuals,   marker="o", label="actual",    linewidth=1.5)
        ax.plot(xs, predicted, marker="s", label="predicted", linewidth=1.5, linestyle="--")
        ax.set_title("Time series")
        ax.set_xlabel("szarża (chronologicznie)")
        ax.set_ylabel("buffer cap (kg/t/ΔpH)")
        ax.legend(fontsize=8)
        step = max(1, len(xs) // 6)
        ax.set_xticks(xs[::step])
        ax.set_xticklabels(labels[::step], rotation=30, fontsize=7)

        # 2. Scatter actual vs predicted
        ax = axes[1]
        all_vals = actuals + predicted
        lo, hi = min(all_vals), max(all_vals)
        ax.scatter(actuals, predicted, alpha=0.7, edgecolors="none")
        ax.plot([lo, hi], [lo, hi], "k--", linewidth=1, label="y=x")
        ax.set_title("Actual vs Predicted")
        ax.set_xlabel("actual buffer cap")
        ax.set_ylabel("predicted buffer cap")
        ax.legend(fontsize=8)

        # 3. Histogram of residuals
        ax = axes[2]
        ax.hist(residuals, bins=max(5, len(rows) // 3), edgecolor="white")
        ax.axvline(0, color="k", linewidth=1, linestyle="--")
        ax.set_title("Residuals (predicted − actual)")
        ax.set_xlabel("residual (kg/t/ΔpH)")
        ax.set_ylabel("count")
    else:
        for ax in axes:
            ax.text(0.5, 0.5, "Brak danych", ha="center", va="center",
                    transform=ax.transAxes, color="gray")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    return stats, buf.getvalue()


def generate_chart_response(db: sqlite3.Connection,
                            produkt: str = "Chegina_K7") -> dict[str, Any]:
    """Return {stats, chart_png_b64} suitable for JSON response."""
    stats, png_bytes = generate_chart_png(db, produkt)
    return {
        "stats": stats,
        "chart_png_b64": base64.b64encode(png_bytes).decode("ascii"),
    }
