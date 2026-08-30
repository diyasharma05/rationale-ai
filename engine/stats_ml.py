"""Traditional statistics / machine-learning detectors — deterministic, non-LLM.

Three components, each independent of the z-score test and of the LLM:

1. ols_forecast / ols_check — ordinary-least-squares trend fit over the KPI's
   history with a 90% prediction interval; the analysis month is flagged when
   the actual lands outside the interval (forecast-based anomaly test).
2. pearson_delta_corr — Pearson correlation between month-over-month changes
   of a driver series and the target KPI: a descriptive co-movement statistic
   for the causal links declared in the semantic contract.
3. iforest_daily — scikit-learn IsolationForest trained on trailing daily-grain
   data (value, day-of-week, ratio-to-rolling-mean), scored on the analysis
   month: an ML detector at a finer grain than any monthly test. Seeded, so
   results are reproducible run to run.
"""
import numpy as np
import pandas as pd

# two-sided 90% t critical values by degrees of freedom (standard for
# directional KPI monitoring; a 95% band is looser than the z-gate itself)
_T90 = {1: 6.314, 2: 2.920, 3: 2.353, 4: 2.132, 5: 2.015, 6: 1.943, 7: 1.895,
        8: 1.860, 9: 1.833, 10: 1.812, 11: 1.796, 12: 1.782, 13: 1.771, 14: 1.761}


def _t90(df: int) -> float:
    if df in _T90:
        return _T90[df]
    return 1.75 if df > 14 else 6.314


def ols_forecast(hist, horizon: int = 3) -> dict:
    """Fit y = b0 + b1*t on the history and forecast `horizon` steps ahead
    with a 90% prediction interval."""
    y = np.asarray(hist, dtype=float)
    n = len(y)
    x = np.arange(n, dtype=float)
    b1, b0 = np.polyfit(x, y, 1)
    yhat = b0 + b1 * x
    sse = float(np.sum((y - yhat) ** 2))
    s = (sse / (n - 2)) ** 0.5 if n > 2 else 0.0
    # floor the residual scale (same guard as the z-detector) so a perfectly
    # flat/linear history cannot collapse the interval to zero width
    s = max(s, abs(float(np.mean(y))) * 1e-6, 1e-9)
    sxx = float(np.sum((x - x.mean()) ** 2)) or 1e-9
    t = _t90(n - 2)
    xs = np.arange(n, n + horizon, dtype=float)
    pred = b0 + b1 * xs
    se = s * np.sqrt(1 + 1 / n + (xs - x.mean()) ** 2 / sxx)
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - sse / ss_tot if ss_tot > 1e-12 else 0.0
    return {"pred": pred.tolist(), "lo": (pred - t * se).tolist(),
            "hi": (pred + t * se).tolist(), "slope": float(b1),
            "r2": round(float(r2), 3), "level": 90, "n": n}


def ols_check(hist, actual) -> dict | None:
    """Forecast one step and test whether the actual falls outside the 90% PI."""
    if actual is None or len(hist) < 6:
        return None
    fc = ols_forecast(hist, horizon=1)
    lo, hi, pred = fc["lo"][0], fc["hi"][0], fc["pred"][0]
    return {"pred": pred, "lo": lo, "hi": hi, "r2": fc["r2"],
            "outside": bool(actual < lo or actual > hi)}


def pearson_delta_corr(target_vals, driver_vals) -> float | None:
    """Pearson r between month-over-month pct changes of two period-aligned
    series (caller must align by period before passing values)."""
    a = np.asarray(target_vals, dtype=float)
    b = np.asarray(driver_vals, dtype=float)
    if len(a) != len(b) or len(a) < 7:
        return None
    with np.errstate(divide="ignore", invalid="ignore"):
        da = np.diff(a) / np.where(np.abs(a[:-1]) < 1e-9, np.nan, np.abs(a[:-1]))
        db = np.diff(b) / np.where(np.abs(b[:-1]) < 1e-9, np.nan, np.abs(b[:-1]))
    mask = ~(np.isnan(da) | np.isnan(db))
    if mask.sum() < 6:
        return None
    da, db = da[mask], db[mask]
    if da.std() < 1e-12 or db.std() < 1e-12:
        return None
    return round(float(np.corrcoef(da, db)[0, 1]), 2)


def iforest_daily(daily_df: pd.DataFrame, period: str) -> dict | None:
    """daily_df: columns [date, region, value] at daily grain. Trains one
    IsolationForest PER REGION on that region's days before the analysis month
    (features: value, ratio to 7-day rolling mean, day-of-week), then scores
    the month's days. Localizes the anomaly: a regional level shift that
    national totals smooth over lights up in its own region's model."""
    from sklearn.ensemble import IsolationForest

    df = daily_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    month = pd.Period(period, freq="M")
    # Raw daily revenue is too noisy (Poisson on lumpy enterprise orders) for a
    # per-day outlier test to see a level shift, so the observation unit is the
    # 7-day smoothed level: roll7 (absolute) and roll7/roll90 (relative to the
    # region's long-run level — a persistent shift cannot hide from this).
    feats = ["roll7", "ratio"]

    region_stats = {}
    for region, g in df.groupby("region"):
        g = g.groupby("date", as_index=False)["value"].sum().sort_values("date")
        g["roll7"] = g["value"].rolling(7, min_periods=3).mean()
        roll90 = g["value"].rolling(90, min_periods=30).mean()
        g["ratio"] = (g["roll7"] / roll90).fillna(1.0)
        g = g.dropna(subset=["roll7"])
        is_month = g["date"].dt.to_period("M") == month
        train, test = g[g["date"].dt.to_period("M") < month], g[is_month]
        if len(train) < 90 or len(test) < 10:
            continue
        model = IsolationForest(n_estimators=200, contamination=0.03, random_state=42)
        model.fit(train[feats])
        flags = model.predict(test[feats]) == -1
        region_stats[region] = {
            "n_flagged": int(flags.sum()), "n_days": int(len(test)),
            "rate": round(float(flags.mean()), 3),
        }
    if not region_stats:
        return None
    top_region = max(region_stats, key=lambda r: region_stats[r]["rate"])
    top = region_stats[top_region]
    # fixed decision rule: >10% of the month's days anomalous in some region.
    # (Re-predicting the training set just echoes the contamination setting,
    # so it is reported for context but is not the threshold.)
    flagged = top["rate"] > 0.10
    return {"n_days": top["n_days"], "n_flagged": top["n_flagged"],
            "contamination": 0.03, "n_models": len(region_stats),
            "region_counts": {r: s["n_flagged"] for r, s in region_stats.items()
                              if s["n_flagged"] > 0},
            "top_region": top_region if top["n_flagged"] > 0 else None,
            "flagged": bool(flagged)}
