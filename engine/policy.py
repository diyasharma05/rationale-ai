"""Business policy: how movements are prioritised, and who may act on them.

Neither of these is rendering. Triage order is the answer to "what should this
person look at first", and decision rights come out of the semantic contract --
both are governance decisions that happen to have been living in the view layer,
where they could not be unit-tested.
"""

NO_OWNER = "—"


def severity_order(scan: dict) -> list:
    """Objective 1: flagged first (worst first), then sparse, then quiet.

    `scan` maps kpi_id -> (cfg, series, anomaly).
    """
    def key(item):
        _, (_cfg, _series, an) = item
        if an["material"]:
            return (0, -abs(an["z"] or 0))
        if an["sparse"]:
            return (1, 0)
        return (2, 0)
    return [k for k, _ in sorted(scan.items(), key=key)]


def lever_approval(cfg: dict, lever_text: str) -> str:
    """Who must sign off on a lever, per the KPI's contract.

    Matching is fuzzy because the lever text on an action card is written by
    the model from the contract's lever name, so it can be a paraphrase.
    """
    if not lever_text:
        return NO_OWNER
    for lever in cfg.get("levers", []):
        name = lever["lever"]
        if name == lever_text or name in lever_text or lever_text in name:
            return lever.get("approval", NO_OWNER)
    return NO_OWNER
