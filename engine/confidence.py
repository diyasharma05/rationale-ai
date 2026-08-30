"""Confidence scoring — deterministic, non-LLM. The score arithmetic never
comes from the LLM; Claude only supplies which evidence snippet supports
which hypothesis, and even that mapping is counted (not scored) here.

score = 0.35 * signal_strength        (|z| capped at 4 -> [0,1])
      + 0.35 * driver_coverage        (consistent drivers / total drivers)
      + 0.30 * evidence_agreement     (hypotheses corroborated by unstructured
                                       or external evidence / total hypotheses)
Sparse-history KPIs are capped at 0.40 regardless.

Gates: SIGNAL   = materiality test from the contract (checked upstream)
       EVIDENCE = score >= 0.60 to state a root cause
       ACTION   = score >= 0.75 to emit recommended actions
"""
EVIDENCE_GATE = 0.60
ACTION_GATE = 0.75
SPARSE_CAP = 0.40

WEIGHTS = {"signal": 0.35, "coverage": 0.35, "evidence": 0.30}


def signal_strength(z) -> float:
    return min(abs(z or 0) / 3.0, 1.0)  # |z| >= 3 counts as a fully established signal


def driver_coverage(driver_findings) -> float:
    if not driver_findings:
        return 0.5  # no declared drivers -> neutral prior
    n_cons = sum(1 for d in driver_findings if d["status"] == "consistent")
    n_contra = sum(1 for d in driver_findings if d["status"] == "contradicts")
    raw = n_cons / len(driver_findings)
    # contradicting drivers actively reduce trust in a causal story
    return max(0.0, raw - 0.25 * n_contra)


def evidence_agreement(hypotheses) -> float:
    if not hypotheses:
        return 0.0
    corroborated = sum(1 for h in hypotheses if h.get("snippets") or h.get("events"))
    return corroborated / len(hypotheses)


def score(z, driver_findings, hypotheses, sparse=False) -> dict:
    comps = {
        "signal": round(signal_strength(z), 3),
        "coverage": round(driver_coverage(driver_findings), 3),
        "evidence": round(evidence_agreement(hypotheses), 3),
    }
    s = sum(WEIGHTS[k] * comps[k] for k in WEIGHTS)
    capped = False
    if sparse and s > SPARSE_CAP:
        s, capped = SPARSE_CAP, True
    return {"value": round(s, 3), "components": comps, "weights": WEIGHTS,
            "sparse_capped": capped,
            "evidence_gate": s >= EVIDENCE_GATE, "action_gate": s >= ACTION_GATE}
