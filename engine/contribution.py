"""Contribution analysis — deterministic, non-LLM.

For each contract-listed dimension: compare the analysis month's per-member
values against the average of the prior three months.

Two things this deliberately does NOT do:

* It does not report a "share of the movement" for KPIs whose members do not
  sum to the national value. A percentage (fulfilment SLA, marketing
  conversion) or an average (AOV) cannot be decomposed additively -- the
  per-region percentage-point deltas do not add up to the shipment-weighted
  national delta -- so for those the per-member LEVEL change is the honest
  output. Which KPIs are additive is declared in the semantic contract
  (`dim_additive`), not guessed from the unit string.

* It does not pick a "focus region" out of noise. Focus is only claimed when a
  member accounts for a large share of the movement IN THE DIRECTION THAT
  HURTS; otherwise the movement is reported as diffuse. Selecting on |share|
  used to put improving regions into focus (West entered the complaint-rate
  focus because complaints FELL there), and falling back to "largest |delta|"
  used to pick a region that beat the next one by ~1% of noise.
"""
import pandas as pd

from . import db

FOCUS_SHARE = 0.35          # share of the harmful movement to count as a focus
MAX_FOCUS = 2


def _prior_months(period: str, n: int = 3):
    p = pd.Period(period, freq="M")
    return [str(p - i) for i in range(1, n + 1)]


def breakdown(kpi_id: str, dim: str, period: str, role_id: str,
              additive: bool = True) -> pd.DataFrame:
    cur = db.dim_breakdown(kpi_id, dim, period, role_id).rename(columns={"value": "current"})
    bases = []
    for m in _prior_months(period):
        b = db.dim_breakdown(kpi_id, dim, m, role_id)
        if not b.empty:
            bases.append(b)
    if not bases:
        cur["baseline"] = 0.0
    else:
        base = pd.concat(bases).groupby("member", as_index=False)["value"].mean() \
                 .rename(columns={"value": "baseline"})
        cur = cur.merge(base, on="member", how="outer").fillna(0.0)
    cur["delta"] = cur["current"] - cur["baseline"]

    net = float(cur["delta"].sum())
    gross = float(cur["delta"].abs().sum())
    if not additive:
        # a share of a non-additive total is not a quantity
        cur["share_of_delta"] = pd.NA
    elif gross > 1e-9 and abs(net) >= 0.5 * gross:
        cur["share_of_delta"] = cur["delta"] / net
    else:
        # Heavy cancellation: the net denominator is small relative to the
        # movement it is dividing, so shares blow up past 1 and flip sign on
        # rounding. The old guard only caught exact cancellation.
        cur["share_of_delta"] = pd.NA
    return cur.sort_values("delta", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def focus_members(table: pd.DataFrame, good_direction: str = "up"):
    """Members driving the movement in the harmful direction.

    Returns (members, concentration). `concentration` is "diffuse" when no
    single member stands out — a real and useful finding (a uniform drop across
    every region points at something systemic, like a tracking change, rather
    than anything regional).
    """
    if table is None or table.empty or "delta" not in table:
        return [], "none"
    harmful_sign = 1.0 if good_direction == "down" else -1.0
    bad = table[table["delta"] * harmful_sign > 0]
    gross_bad = float(bad["delta"].abs().sum())
    if bad.empty or gross_bad <= 1e-9:
        return [], "none"
    shares = (bad["delta"].abs() / gross_bad)
    picked = list(bad.loc[shares >= FOCUS_SHARE, "member"].head(MAX_FOCUS))
    return (picked, "concentrated") if picked else ([], "diffuse")


def top_contributors(kpi_id: str, cfg: dict, period: str, role_id: str) -> dict:
    """Run every contract dimension; return per-dim tables + focus regions."""
    additive = bool(cfg.get("dim_additive", True))
    result = {}
    for dim in cfg.get("dimensions", []):
        try:
            result[dim] = breakdown(kpi_id, dim, period, role_id, additive=additive)
        except Exception as e:  # a dim missing in a source shouldn't kill the run
            result[dim] = pd.DataFrame({"member": [f"error: {e}"], "current": [0],
                                        "baseline": [0], "delta": [0],
                                        "share_of_delta": [pd.NA]})
    focus_regions, concentration = focus_members(
        result.get("region"), cfg.get("good_direction", "up"))
    return {"tables": result, "focus_regions": focus_regions,
            "concentration": concentration, "additive": additive}
