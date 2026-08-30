"""Contribution analysis — deterministic, non-LLM.

For each contract-listed dimension: compare the analysis month's per-member
values against the average of the prior three months, and report each
member's share of the total movement (share is only meaningful for additive
KPIs; for rates the per-member delta is reported as a level change).
"""
import pandas as pd

from . import db


def _prior_months(period: str, n: int = 3):
    p = pd.Period(period, freq="M")
    return [str(p - i) for i in range(1, n + 1)]


def breakdown(kpi_id: str, dim: str, period: str, role_id: str) -> pd.DataFrame:
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
    total = cur["delta"].sum()
    cur["share_of_delta"] = cur["delta"] / total if abs(total) > 1e-9 else 0.0
    return cur.sort_values("delta", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def top_contributors(kpi_id: str, cfg: dict, period: str, role_id: str) -> dict:
    """Run every contract dimension; return per-dim tables + focus regions."""
    result = {}
    for dim in cfg.get("dimensions", []):
        try:
            result[dim] = breakdown(kpi_id, dim, period, role_id)
        except Exception as e:  # a dim missing in a source shouldn't kill the run
            result[dim] = pd.DataFrame({"member": [f"error: {e}"], "current": [0],
                                        "baseline": [0], "delta": [0], "share_of_delta": [0]})
    focus_regions = []
    if "region" in result and not result["region"].empty:
        reg = result["region"]
        focus_regions = list(reg.loc[reg["share_of_delta"].abs() >= 0.35, "member"].head(2))
        if not focus_regions:
            focus_regions = [reg.iloc[0]["member"]]
    return {"tables": result, "focus_regions": focus_regions}
