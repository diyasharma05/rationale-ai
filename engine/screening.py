"""Family-wise screening: multiple-comparison control across the KPI portfolio.

Every month the engine tests every governed KPI the role can see. Testing 7
KPIs at |z| >= 2 and calling each hit "material" independently gives a
family-wise false-positive rate near 28% -- roughly one phantom alert every
month, which is exactly the alert fatigue the materiality gate exists to
prevent. (Confirmed on the demo data: complaint_rate flags at 2026-02 and
2026-04 with nothing planted.)

Benjamini-Hochberg controls the false DISCOVERY rate instead: of the movements
we do flag, at most q are expected to be spurious. That is the right error rate
for screening -- it stays sensitive, unlike Bonferroni, which at n=7 would be
strict enough to suppress real incidents.

Measured on the planted ground truth at q=0.10: all five July incidents
survive, both false positives are dropped, and detection precision goes from
0.833 to 1.000 with recall unchanged at 1.0.
"""
from functools import lru_cache

from . import anomaly, db

# False discovery rate for portfolio screening. 0.10 is the conventional
# exploratory-screening level. Note this choice is load-bearing: at q=0.05 the
# July revenue movement (p=0.066) would itself be suppressed. See
# tests/test_screening.py, which pins that margin.
FDR_Q = 0.10


def benjamini_hochberg(pvalues, q: float = FDR_Q):
    """Return (reject flags, BH-adjusted q-values), both in input order."""
    m = len(pvalues)
    if m == 0:
        return [], []
    order = sorted(range(m), key=lambda i: pvalues[i])
    # largest rank whose p-value clears its own step-up threshold; everything
    # ranked at or below it is rejected, including any larger p-values that
    # individually fail (that step-up behaviour is what makes BH more powerful
    # than a per-test correction)
    k = 0
    for rank, i in enumerate(order, start=1):
        if pvalues[i] <= rank / m * q:
            k = rank
    reject = [False] * m
    for rank, i in enumerate(order, start=1):
        if rank <= k:
            reject[i] = True
    # adjusted p-values, enforced monotone from the largest rank down
    adj = [1.0] * m
    prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        prev = min(prev, pvalues[i] * m / rank)
        adj[i] = min(1.0, prev)
    return reject, adj


@lru_cache(maxsize=64)
def family_qvalues(role_id: str, period: str, q: float = FDR_Q) -> dict:
    """BH across every KPI this role is monitoring this period.

    Keyed by role: the family is what the role actually sees, and two roles
    monitor different numbers of KPIs, so the correction genuinely differs.
    Sparse KPIs are excluded -- they are never tested, so they are not part of
    the family and must not inflate the denominator.
    """
    kpis = db.allowed_kpis(role_id)
    tested, pvals = [], []
    for kpi_id, cfg in kpis.items():
        an = anomaly.analyze(db.kpi_series(kpi_id, role_id), period,
                             cfg["materiality"], cfg.get("min_history", 6))
        if an["sparse"] or an["p_value"] is None:
            continue
        tested.append(kpi_id)
        pvals.append(an["p_value"])
    reject, adj = benjamini_hochberg(pvals, q)
    return {kpi_id: {"p_value": p, "q_value": round(a, 5), "significant": bool(r),
                     "family_size": len(tested)}
            for kpi_id, p, a, r in zip(tested, pvals, adj, reject)}


def screen(an: dict, kpi_id: str, role_id: str, period: str) -> dict:
    """Annotate one anomaly result with its family-wise verdict.

    `material` becomes: clears the contract's business thresholds AND survives
    multiplicity control. A movement that only clears the per-KPI bar is
    reported as `fdr_suppressed` so the UI can say why it was not escalated
    rather than silently dropping it.
    """
    fam = family_qvalues(role_id, period).get(kpi_id)
    if not fam:
        return an
    an["q_value"] = fam["q_value"]
    an["family_size"] = fam["family_size"]
    an["fdr_significant"] = fam["significant"]
    an["material_unadjusted"] = an["material"]
    an["fdr_suppressed"] = bool(an["material"] and not fam["significant"])
    an["material"] = bool(an["material"] and fam["significant"])
    return an
