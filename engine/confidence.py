"""Confidence scoring — deterministic, non-LLM. The score arithmetic never
comes from the LLM; Claude only supplies which evidence snippet supports which
hypothesis, and even that mapping is counted (not scored) here.

    score = w_signal   * signal_strength     (|z| capped at 3 -> [0,1])
          + w_coverage * driver_coverage     (declared drivers that co-moved)
          + w_evidence * evidence_agreement  (hypotheses with corroboration)

Three properties this deliberately has:

1. **It cannot reach 1.0.** The ratio components are Laplace-smoothed, so "1 of
   1 corroborated" scores 2/3 rather than certainty. One month of data, n~11,
   a single corroborating document, and no counterfactual is not grounds for
   claiming complete confidence -- and the previous formulation did exactly
   that (enterprise_active_accounts scored a displayed 1.000).

2. **Absence of evidence is not credit.** A KPI with no declared drivers used
   to receive a flat 0.5 "neutral prior" for coverage, i.e. 0.175 of the total
   score for having nothing to check -- which was most of what pushed
   fulfilment_sla through the action gate. Unassessable components are now
   dropped and the remaining weights renormalised, so the score says "this is
   what we could actually assess", not "we assume half marks".

3. **A driver nothing explains counts for less.** A co-moving driver flagged
   `unexplained` (it moved, but none of its own declared drivers did) counts
   at half weight. This is what keeps the planted marketing tracking bug -- a
   measurement artifact -- from corroborating the revenue drop.

Gates: SIGNAL   = materiality + multiplicity control (checked upstream)
       EVIDENCE = score >= 0.60 to state a root cause
       ACTION   = score >= 0.75 to recommend actions
The gate values are unchanged from the earlier scale, but they are now
*validated* rather than asserted: eval.py checks that every planted case lands
in the intended band. See tests/test_confidence.py.
"""
EVIDENCE_GATE = 0.60
ACTION_GATE = 0.75
SPARSE_CAP = 0.40

# Hard ceiling. The Laplace smoothing already makes 1.0 unreachable; this is a
# belt-and-braces guarantee so no future change to the components can put a
# claim of total certainty on screen.
MAX_CONFIDENCE = 0.95

WEIGHTS = {"signal": 0.35, "coverage": 0.35, "evidence": 0.30}

UNEXPLAINED_WEIGHT = 0.5      # a lead, not corroboration

# Verifiability discount. Renormalising over the assessable components alone
# has a perverse consequence: a KPI with no declared drivers is scored on two
# strong channels instead of three, so REMOVING a checkable dimension raises
# its score. (Measured: fulfilment_sla scored 0.885 against revenue's 0.715
# precisely because revenue could be cross-checked against four drivers and
# fulfilment_sla could not be cross-checked at all.) A conclusion resting on
# fewer independent channels is less established, so the weighted mean is
# scaled by how much of the total weight we were actually able to assess.
# This is a judgement call, stated openly, and pinned by a test.
ASSESSED_FLOOR = 0.85


def signal_strength(z) -> float:
    return min(abs(z or 0) / 3.0, 1.0)  # |z| >= 3 counts as a fully established signal


def driver_coverage(driver_findings):
    """Share of declared drivers that co-moved, Laplace-smoothed.

    Returns None when the KPI declares no drivers: that is *unassessable*, not
    neutral, and the caller renormalises the remaining weights instead of
    handing out half marks.
    """
    if not driver_findings:
        return None
    credit = 0.0
    for d in driver_findings:
        if d["status"] == "co_moves":
            credit += UNEXPLAINED_WEIGHT if d.get("unexplained") else 1.0
    n_contra = sum(1 for d in driver_findings if d["status"] == "contradicts")
    n = len(driver_findings)
    raw = (credit + 1.0) / (n + 2.0)          # Laplace: 1-of-1 is not certainty
    # contradicting drivers actively reduce trust in a causal story
    return max(0.0, raw - 0.25 * n_contra)


def evidence_agreement(hypotheses):
    """Share of hypotheses with corroboration, Laplace-smoothed.

    Zero (not smoothed) when there are no hypotheses at all: nothing to
    corroborate is an absence of evidence, and smoothing it would hand out
    free credit for having found no explanation.
    """
    if not hypotheses:
        return 0.0
    corroborated = sum(1 for h in hypotheses if h.get("snippets") or h.get("events"))
    return (corroborated + 1.0) / (len(hypotheses) + 2.0)


def score(z, driver_findings, hypotheses, sparse=False) -> dict:
    comps = {
        "signal": round(signal_strength(z), 3),
        "coverage": driver_coverage(driver_findings),
        "evidence": round(evidence_agreement(hypotheses), 3),
    }
    if comps["coverage"] is not None:
        comps["coverage"] = round(comps["coverage"], 3)
    # renormalise over the components we could actually assess
    usable = {k: v for k, v in comps.items() if v is not None}
    assessed_w = sum(WEIGHTS[k] for k in usable)
    total_w = assessed_w or 1.0
    s = sum(WEIGHTS[k] * v for k, v in usable.items()) / total_w
    # scale by breadth of assessment (see ASSESSED_FLOOR)
    breadth = assessed_w / sum(WEIGHTS.values())
    s *= ASSESSED_FLOOR + (1.0 - ASSESSED_FLOOR) * breadth
    capped = False
    if sparse and s > SPARSE_CAP:
        s, capped = SPARSE_CAP, True
    if s > MAX_CONFIDENCE:
        s = MAX_CONFIDENCE
    return {"value": round(s, 3), "components": comps, "weights": WEIGHTS,
            "assessed": sorted(usable), "sparse_capped": capped,
            "breadth": round(breadth, 3),
            "evidence_gate": s >= EVIDENCE_GATE, "action_gate": s >= ACTION_GATE}
