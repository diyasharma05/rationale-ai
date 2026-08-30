"""Signal detection — deterministic, non-LLM.

Method (V0): z-score of the analysis month against the trailing history
(12-month stationary baseline; STL deseasonalization is on the roadmap),
plus a percent change against the trailing-3-month average. A movement is
*material* only if it clears BOTH the statistical threshold (|z|) and the
business-impact threshold (|pct|) from the KPI's semantic contract.
"""
import numpy as np
import pandas as pd


def analyze(series: pd.DataFrame, period: str, materiality: dict, min_history: int = 6) -> dict:
    """series: df[period 'YYYY-MM', value]; period: analysis month 'YYYY-MM'."""
    s = series[series["period"] <= period].reset_index(drop=True)
    out = {"period": period, "n_history": max(len(s) - 1, 0), "sparse": False,
           "current": None, "z": None, "pct_vs_recent": None, "material": False,
           "mean": None, "std": None}
    if s.empty or s.iloc[-1]["period"] != period:
        out["sparse"] = True
        out["note"] = "no data for the analysis period"
        return out
    cur = float(s.iloc[-1]["value"])
    hist = s.iloc[:-1]["value"].astype(float).to_numpy()
    out["current"] = cur
    if len(hist) < min_history:
        out["sparse"] = True
        out["note"] = f"only {len(hist)} historical period(s); {min_history} required for causal claims"
        if len(hist) >= 1:
            out["mean"] = float(np.mean(hist))
        return out
    mean, raw_std = float(np.mean(hist)), float(np.std(hist, ddof=1))
    std = max(raw_std, abs(mean) * 1e-6, 1e-9)
    z = (cur - mean) / std
    if raw_std <= max(abs(mean) * 1e-6, 1e-9):
        # (near-)constant history: z is unbounded and meaningless — cap it so a
        # real level shift reads as "off the charts" instead of z = -157894
        z = 0.0 if cur == mean else float(np.sign(cur - mean)) * 9.99
    recent = float(np.mean(hist[-3:]))
    pct = (cur - recent) / abs(recent) * 100 if recent else 0.0
    out.update(mean=mean, std=std, z=round(z, 2), pct_vs_recent=round(pct, 2))
    out["material"] = (abs(z) >= materiality.get("min_abs_z", 2.0)
                       and abs(pct) >= materiality.get("min_pct", 0.0))
    # second, independent detector: OLS trend forecast + 90% prediction interval
    from . import stats_ml
    out["forecast_check"] = stats_ml.ols_check(hist, cur)
    return out
