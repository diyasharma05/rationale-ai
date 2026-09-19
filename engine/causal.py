"""Causal inference, honestly scoped: difference-in-differences on the regional panel.

Everything else in the engine tests CONCURRENT movement (drivers.py says so in
its first paragraph). This module is the one place a causal quantity is
estimated, and it is estimated the classical way: the regions the contribution
analysis puts in focus are the treated units, the other regions the role can see
are the controls, the three months before the analysis month are the
pre-period, and the analysis month is the post-period. The effect is the
difference of the two differences.

What that buys, and what it costs, in one place:

* It gives an EFFECT SIZE with an interval ("the North-West shock cost about
  ₹X per day, 95% CI [a, b]"), which no amount of co-movement can.
* It rests on an assumption the data can partly check: that treated and control
  regions would have moved in parallel without the shock. The check is a
  placebo estimate on the pre-period alone; if that is not near zero the
  estimate is reported with the warning, not withheld and not dressed up.
* It is only identifiable when there IS an untreated comparison group. A
  movement spread evenly across every region (the planted tracking bug) has no
  controls, and the honest output is "not identifiable", stated as such.
* With five regions, permutation inference cannot reach below p = 0.2, so the
  bootstrap interval carries the precision claim and the placebo-region effects
  are shown for what they are: a small reference distribution.

The engine's confidence score is deliberately NOT changed by this estimate.
Adding a component would move every calibrated gate; the estimate is evidence
shown beside the verdict, and the narrative may quote it with its assumption.

Implementation note: the panel is balanced (every region, every week), so the
estimate reduces to the mean over post weeks minus the mean over pre weeks of a
single per-week series -- treated-region mean minus control-region mean. The
bootstrap resamples weeks of that series, which keeps whole weeks (and so any
common shock in them) together, and runs in milliseconds.
"""
from functools import lru_cache

import numpy as np
import pandas as pd

from . import db, stream

PRE_MONTHS = 3
BOOTSTRAP = 400
SEED = 42
MIN_WEEKS = 3            # per window before an estimate is attempted

# KPI -> (numerator, denominator or None, unit, plain-words measure)
_MEASURES = {
    "revenue":              ("revenue",     None,       "INR/day",         "mean daily revenue"),
    "aov":                  ("revenue",     "orders",   "INR",             "revenue per order"),
    "fulfilment_sla":       ("sla",         None,       "%",               "share of shipments within SLA"),
    "complaint_rate":       ("complaints",  "orders",   "per 1000 orders", "complaints per 1,000 orders"),
    "marketing_conversion": ("conversions", "sessions", "%",               "conversions per session"),
}


@lru_cache(maxsize=8)
def _weekly_marketing(role_id: str) -> pd.DataFrame:
    df = db.query("SELECT CAST(week_start AS DATE) AS day, region, sessions, conversions "
                  "FROM marketing_weekly WHERE 1=1" + db.role_where(role_id))
    df["day"] = pd.to_datetime(df["day"]).dt.date
    return df


def _panel(kpi_id: str, role_id: str) -> pd.DataFrame | None:
    """(week, region, y) for the KPI, weekly to damp day-level noise."""
    if kpi_id not in _MEASURES:
        return None
    num, den, _unit, _label = _MEASURES[kpi_id]
    if kpi_id == "marketing_conversion":
        d = _weekly_marketing(role_id).copy()
    else:
        d = stream._daily_region(role_id).copy()
    dt = pd.to_datetime(d["day"])
    d["week"] = dt - pd.to_timedelta(dt.dt.weekday, unit="D")
    if kpi_id == "fulfilment_sla":
        d["sla"] = d["shipments"] - d["breaches"]
        den = "shipments"
    agg = {"num": (num, "sum"), "days": ("day", "nunique")}
    if den:
        agg["den"] = (den, "sum")
    g = d.groupby(["week", "region"], as_index=False).agg(**agg)
    if den:
        g["y"] = g["num"] / g["den"].replace(0, np.nan)
        if kpi_id in ("fulfilment_sla", "marketing_conversion"):
            g["y"] *= 100.0
        elif kpi_id == "complaint_rate":
            g["y"] *= 1000.0
    else:
        g["y"] = g["num"] / g["days"]                       # per-day mean within the week
    g["week"] = pd.to_datetime(g["week"])
    return g[["week", "region", "y"]].dropna()


def _week_diffs(p: pd.DataFrame, treated: set) -> pd.Series:
    """Per week: mean over treated regions minus mean over control regions."""
    t = p[p["region"].isin(treated)].groupby("week")["y"].mean()
    c = p[~p["region"].isin(treated)].groupby("week")["y"].mean()
    return (t - c).dropna()


def _did(d: pd.Series, pre_weeks, post_weeks) -> float:
    return float(d.reindex(post_weeks).mean() - d.reindex(pre_weeks).mean())


def _bootstrap_ci(d: pd.Series, pre_weeks, post_weeks, rng) -> list:
    pre = d.reindex(pre_weeks).to_numpy()
    post = d.reindex(post_weeks).to_numpy()
    ip = rng.integers(0, len(pre), size=(BOOTSTRAP, len(pre)))
    iq = rng.integers(0, len(post), size=(BOOTSTRAP, len(post)))
    effs = post[iq].mean(axis=1) - pre[ip].mean(axis=1)
    lo, hi = np.percentile(effs, [2.5, 97.5])
    return [float(lo), float(hi)]


def estimate(kpi_id: str, period: str, role_id: str, treated_regions: list, an: dict = None) -> dict:
    """Difference-in-differences for the analysis month against the prior
    PRE_MONTHS, treated = the focus regions, controls = every other region the
    role can see. Returns identifiable=False with a reason when the design is
    not available, rather than a number that means nothing."""
    base = {"method": "difference-in-differences (weekly regional panel)", "kpi": kpi_id,
            "period": period, "treated": list(treated_regions or []), "identifiable": False}
    if kpi_id not in _MEASURES:
        return {**base, "reason": "no regional panel is defined for this KPI at daily grain"}
    if not treated_regions:
        return {**base, "reason": "the movement is spread across every region, so there is no "
                                  "untreated comparison group; the effect is not identifiable"}
    p = _panel(kpi_id, role_id)
    if p is None or p.empty:
        return {**base, "reason": "no panel rows"}
    regions = sorted(p["region"].unique())
    treated = {r for r in treated_regions if r in regions}
    controls = [r for r in regions if r not in treated]
    if not treated:
        return {**base, "reason": "the focus regions are not visible to this role"}
    if not controls:
        return {**base, "reason": "every region this role can see is treated; no comparison group"}
    post_start = pd.Timestamp(period + "-01")
    post_end = post_start + pd.offsets.MonthEnd(0)
    pre_start = post_start - pd.DateOffset(months=PRE_MONTHS)
    window = p[(p["week"] >= pre_start) & (p["week"] <= post_end)]
    d = _week_diffs(window, treated)
    pre_weeks = [w for w in d.index if w < post_start]
    post_weeks = [w for w in d.index if w >= post_start]
    if len(pre_weeks) < MIN_WEEKS or len(post_weeks) < MIN_WEEKS:
        return {**base, "reason": f"too few weeks ({len(pre_weeks)} pre, {len(post_weeks)} post) for an estimate"}

    rng = np.random.default_rng(SEED)
    effect = _did(d, pre_weeks, post_weeks)
    ci = _bootstrap_ci(d, pre_weeks, post_weeks, rng)

    # parallel-trends check: the same estimator on the pre-period alone
    half = len(pre_weeks) // 2
    early, late = pre_weeks[:half], pre_weeks[half:]
    pre_eff = _did(d, early, late)
    pre_ci = _bootstrap_ci(d, early, late, rng)
    pretrend_ok = pre_ci[0] <= 0.0 <= pre_ci[1]

    # placebo regions: pretend each control was the treated one
    placebo = {}
    others = window[~window["region"].isin(treated)]
    if others["region"].nunique() >= 2:
        for c in controls:
            dc = _week_diffs(others, {c})
            placebo[c] = _did(dc, [w for w in dc.index if w < post_start], [w for w in dc.index if w >= post_start])
    rank = 1 + sum(1 for v in placebo.values() if abs(v) >= abs(effect))
    perm_p = rank / (len(placebo) + 1) if placebo else None

    _num, _den, unit, measure = _MEASURES[kpi_id]
    out = {**base, "identifiable": True, "treated": sorted(treated), "controls": controls,
           "weak_controls": len(controls) < 2, "unit": unit, "measure": measure,
           "pre_window": [str(pre_weeks[0].date()), str(pre_weeks[-1].date())],
           "post_window": [str(post_weeks[0].date()), str(post_weeks[-1].date())],
           "n_pre_weeks": len(pre_weeks), "n_post_weeks": len(post_weeks),
           "effect": round(effect, 4), "ci95": [round(ci[0], 4), round(ci[1], 4)],
           "ci_excludes_zero": not (ci[0] <= 0.0 <= ci[1]),
           "pretrend": {"effect": round(pre_eff, 4), "ci95": [round(pre_ci[0], 4), round(pre_ci[1], 4)],
                        "parallel_ok": bool(pretrend_ok)},
           "placebo": {"effects": {k: round(v, 4) for k, v in placebo.items()}, "rank": rank,
                       "p": round(perm_p, 3) if perm_p is not None else None,
                       "floor": round(1.0 / (len(placebo) + 1), 3) if placebo else None},
           "assumptions": ("Treated and control regions would have moved in parallel without the "
                           "shock (checked on the pre-period placebo); the shock did not spill into "
                           "control regions; the pre-window is clean. A shock that began before the "
                           "month boundary is partly absorbed into the pre-period, which biases the "
                           "estimate toward zero.")}
    if unit == "INR/day":
        monthly = effect * 30.0 * len(treated)
        out["monthly_effect"] = round(monthly, 2)
        if an and an.get("current") is not None and an.get("mean") is not None:
            total = (an["current"] - an["mean"]) * 30.0
            out["share_of_movement"] = round(monthly / total, 3) if abs(total) > 1e-9 else None
    return out


def summary_line(c: dict) -> str:
    """One deterministic sentence the UI and the template narrative can use."""
    if not c.get("identifiable"):
        return f"Causal estimate not identifiable: {c.get('reason', '')}."
    from . import economics
    lo, hi = c["ci95"]
    if c["unit"] == "INR/day":
        what = f"{economics.fmt_value(c['effect'], 'INR')} per day per treated region"
        band = f"{economics.fmt_value(lo, 'INR')} to {economics.fmt_value(hi, 'INR')}"
    elif c["unit"] == "%":
        what, band = f"{c['effect']:+.2f} percentage points", f"{lo:+.2f} to {hi:+.2f}"
    else:
        what, band = f"{c['effect']:+.2f} {c['unit']}", f"{lo:+.2f} to {hi:+.2f}"
    pt = ("pre-period placebo near zero, so parallel trends look plausible" if c["pretrend"]["parallel_ok"]
          else "pre-period placebo is NOT near zero, so the parallel-trends assumption is doubtful")
    weak = "; only one control region, so treat the interval with caution" if c.get("weak_controls") else ""
    return (f"Difference-in-differences: {', '.join(c['treated'])} versus {', '.join(c['controls'])}, "
            f"{c['measure']}: {what} (95% CI {band}); {pt}{weak}.")


def plain_line(c: dict, fmt) -> str:
    """The executive form: no statistics vocabulary, one number."""
    if not c.get("identifiable"):
        return ""
    where = ", ".join(c["treated"])
    if c.get("monthly_effect") is not None:
        return (f"Compared with the regions that were not affected, the movement in {where} accounts "
                f"for about {fmt(abs(c['monthly_effect']), 'INR')} of this month's change.")
    return (f"Compared with the regions that were not affected, {where} moved by about "
            f"{abs(c['effect']):.1f} {c['unit']} more.")
