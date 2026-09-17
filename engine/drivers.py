"""Driver co-movement check — deterministic, non-LLM.

What this measures, precisely: did another series move in the same period, in
the direction the semantic contract predicts? That is CONCURRENCY, not
causation. The causal claim is imported wholesale from the contract's
`relation: direct|inverse` field, which a human wrote. This module contributes
no evidence about direction of causation: there is no lag structure, no
Granger test, no control for confounders, no counterfactual.

It is still worth computing -- a declared driver that did NOT move is real
evidence against that explanation -- but the output must never be presented as
the engine having discovered a cause.

  co_moves    — driver moved (|z| >= 1.5) in the direction that would be
                consistent with the KPI movement, given the declared relation
  contradicts — driver moved the other way (evidence AGAINST the hypothesis)
  quiet       — no meaningful movement

A co-moving driver that is itself unexplained is flagged `unexplained`: it
moved, but nothing it depends on accounts for why, so it is a lead rather than
corroboration. This is what stops the planted marketing tracking bug (a
measurement artifact whose own drivers are both quiet) from counting as
evidence that it caused the revenue drop.
"""
import math

from . import anomaly, db, stats_ml

DRIVER_Z = 1.5

_LABELS = {
    "co_moves": "moved with it, as the contract predicts (concurrent, not proven causal)",
    "contradicts": "moved the opposite way (evidence against this explanation)",
    "quiet": "did not move meaningfully",
}


def _is_unexplained(d: dict, period: str, role_id: str) -> bool:
    """True when a co-moving driver is a governed KPI that itself moved, but
    none of ITS declared drivers moved -- i.e. nothing upstream accounts for it.

    Looks exactly one level up, never recursively. A driver with no declared
    drivers at all is not judged here (absence of a declared chain is not
    evidence of an unexplained movement).
    """
    if "kpi" not in d:
        return False
    contract = db.load_contract()
    ref = contract["kpis"].get(d["kpi"], {})
    upstream = ref.get("drivers") or []
    if not upstream:
        return False
    for u in upstream:
        if "kpi" in u:
            series = db.kpi_series(u["kpi"], role_id)
        else:
            series = db.metric_series(u["metric_sql"], role_id)
        an = anomaly.analyze(series, period, {"min_abs_z": DRIVER_Z, "min_pct": 0.0})
        if not an["sparse"] and abs(an.get("z") or 0.0) >= DRIVER_Z:
            return False          # something upstream does move with it
    return True


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
            status = "co_moves"
        else:
            status = "contradicts"
        # Deviation from the same baseline the z-score uses. `pct` (vs the
        # trailing 3 months) can disagree in sign with z (vs the long-run mean),
        # and status is decided by z — so any label that pairs z's direction
        # with pct's magnitude can contradict itself.
        mean, cur = an.get("mean"), an.get("current")
        pct_vs_mean = ((cur - mean) / abs(mean) * 100
                       if mean not in (None, 0) and cur is not None else None)
        findings.append({
            "driver_id": driver_id, "label": label, "relation": d["relation"],
            "note": d.get("note", ""), "tags": tags,
            "z": z, "pct": an.get("pct_vs_recent"), "pct_vs_mean": pct_vs_mean,
            "current": an.get("current"),
            "status": status,
            "status_label": _LABELS[status],
            "unexplained": (status == "co_moves"
                            and _is_unexplained(d, period, role_id)),
            "corr": _aligned_corr(parent_series, series, period),
        })
    return findings
