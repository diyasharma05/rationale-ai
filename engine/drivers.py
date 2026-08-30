"""Driver concurrency check — deterministic, non-LLM.

For each driver linked in the KPI's semantic contract (another governed KPI,
or an inline metric with its own SQL), compute the same-period z-score and
classify it against the expected causal relation:

  consistent  — driver moved (|z| >= 1.5) in the direction that would explain
                the KPI movement
  contradicts — driver moved in the direction that should have pushed the KPI
                the *other* way (evidence against the driver hypothesis)
  quiet       — no meaningful movement
"""
import math

from . import anomaly, db, stats_ml

DRIVER_Z = 1.5


def _aligned_corr(parent_series, driver_series, period):
    """Pearson r of MoM changes over the 12 months INCLUDING the analysis month.
    This is a DESCRIPTIVE co-movement statistic, not independent corroboration:
    with ~12 delta pairs, a shared move in the anomaly month dominates r, so it
    must never be presented as historical proof of the causal link (the contract
    declares the link; concurrent movement + evidence corroborate it)."""
    import pandas as pd
    if parent_series is None:
        return None
    m = parent_series.merge(driver_series, on="period", suffixes=("_t", "_d"))
    m = m[m["period"] <= period]
    if len(m) < 7:
        return None
    # reindex to a complete month range so a missing month yields NaN deltas
    # (dropped downstream) instead of a silent cross-gap "MoM" change
    full = pd.period_range(m["period"].min(), m["period"].max(), freq="M").astype(str)
    m = m.set_index("period").reindex(full)
    return stats_ml.pearson_delta_corr(m["value_t"].tolist(), m["value_d"].tolist())


def check_drivers(kpi_cfg: dict, kpi_z: float, period: str, role_id: str,
                  parent_series=None) -> list:
    contract = db.load_contract()
    kpi_sign = math.copysign(1, kpi_z) if kpi_z else 0
    findings = []
    for i, d in enumerate(kpi_cfg.get("drivers", [])):
        if "kpi" in d:
            ref = contract["kpis"][d["kpi"]]
            label, tags = ref["name"], ref.get("tags", [])
            series = db.kpi_series(d["kpi"], role_id)
            driver_id = d["kpi"]
        else:
            label, tags = d.get("label", d["metric"]), [d["metric"]]
            series = db.metric_series(d["metric_sql"], role_id)
            driver_id = d["metric"]
        an = anomaly.analyze(series, period, {"min_abs_z": DRIVER_Z, "min_pct": 0.0})
        z = an.get("z") or 0.0
        moved = abs(z) >= DRIVER_Z and not an["sparse"]
        expected_sign = kpi_sign if d["relation"] == "direct" else -kpi_sign
        if not moved:
            status = "quiet"
        elif math.copysign(1, z) == expected_sign:
            status = "consistent"
        else:
            status = "contradicts"
        findings.append({
            "driver_id": driver_id, "label": label, "relation": d["relation"],
            "note": d.get("note", ""), "tags": tags,
            "z": z, "pct": an.get("pct_vs_recent"), "current": an.get("current"),
            "status": status,
            "corr": _aligned_corr(parent_series, series, period),
        })
    return findings
