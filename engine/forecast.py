"""A forward view, stated with its width.

The sparkline has drawn a three-month OLS trend forecast with a 90% prediction
interval since Round 2; the numbers never reached the narrative or the API.
This gives them a voice, honestly: on these series the linear trend explains
little of the variance (R² is reported), so the forecast is close to "the
mean, plus or minus the normal range". That is still useful -- it is the range
a next month has to leave before anyone should react -- and the two scenarios
frame the decision: what next month looks like if the current movement
persists, and what it looks like if it reverts.

The forecast is anchored on the analysis month and uses only history up to it,
like the anomaly test, so "next month" means the month after the one being
investigated even when the dataset already holds part of it.
"""
import pandas as pd

from . import stats_ml

HORIZON = 3


def next_months(series: pd.DataFrame, an: dict, unit: str) -> dict | None:
    if an.get("sparse") or series is None:
        return None
    s = series[series["period"] <= an["period"]]
    if len(s) < 7:
        return None
    y = [float(v) for v in s["value"]]
    fc = stats_ml.ols_forecast(y, horizon=HORIZON)
    last = pd.Period(an["period"], freq="M")
    periods = [str(last + i) for i in range(1, HORIZON + 1)]
    cur, mean = an.get("current"), an.get("mean")
    return {
        "method": f"OLS trend, {fc['level']}% prediction interval, fit on {fc['n']} months to {an['period']}",
        "periods": periods,
        "pred": [round(v, 4) for v in fc["pred"]],
        "lo": [round(v, 4) for v in fc["lo"]],
        "hi": [round(v, 4) for v in fc["hi"]],
        "r2": fc["r2"],
        "unit": unit,
        "scenarios": {
            "if_persists": round(float(cur), 4) if cur is not None else None,
            "if_reverts": round(float(mean), 4) if mean is not None else None,
        },
        "caveat": ("the trend explains little of the history (R² = %.2f), so the interval is "
                   "essentially the normal range; treat it as the band next month must leave "
                   "before it is news, not as a prediction" % fc["r2"]),
    }


def summary_line(f: dict, fmt) -> str:
    if not f:
        return ""
    nxt = f["periods"][0]
    return (f"Next month ({nxt}), if the trend continues: {fmt(f['pred'][0], f['unit'])}, "
            f"90% interval {fmt(f['lo'][0], f['unit'])} to {fmt(f['hi'][0], f['unit'])}. "
            f"If this month's level persists: {fmt(f['scenarios']['if_persists'], f['unit'])}; "
            f"if it reverts to baseline: {fmt(f['scenarios']['if_reverts'], f['unit'])}.")
