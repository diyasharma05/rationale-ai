"""Business policy: how movements are prioritised, and who may act on them.

Neither of these is rendering. Triage order is the answer to "what should this
person look at first", and decision rights come out of the semantic contract --
both are governance decisions that happen to have been living in the view layer,
where they could not be unit-tested.
"""

import re

NO_OWNER = "—"

# words too common to identify a lever by
_STOPWORDS = {"the", "a", "an", "to", "for", "of", "and", "or", "in", "on",
              "at", "by", "with", "now", "immediately", "open", "plan"}


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


def lever_for(cfg: dict, lever_text: str) -> dict | None:
    """The contract lever an action refers to.

    Matching is fuzzy because the lever text on an action card is written by
    the model from the contract's lever name, so it can be a paraphrase. The
    match is the only thing taken from the model; everything downstream of it
    -- who acts, who approves -- comes from the contract.
    """
    if not lever_text:
        return None
    levers = cfg.get("levers", [])
    for lever in levers:
        name = lever["lever"]
        if name == lever_text or name in lever_text or lever_text in name:
            return lever
    # Substring matching fails the moment the model paraphrases, and an
    # action nobody owns cannot be routed to anyone. Fall back to distinctive-
    # word overlap, requiring a clear winner so a weak match resolves to
    # 'unrouted' rather than to the wrong person.
    words = set(re.findall(r"[a-z0-9]+", lever_text.lower())) - _STOPWORDS
    if not words:
        return None
    scored = []
    for lever in levers:
        lw = set(re.findall(r"[a-z0-9]+", lever["lever"].lower())) - _STOPWORDS
        scored.append((len(words & lw), lever))
    scored.sort(key=lambda s: -s[0])
    if scored and scored[0][0] >= 2 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    return None


def lever_approval(cfg: dict, lever_text: str) -> str:
    """Who must sign off, per the contract."""
    lever = lever_for(cfg, lever_text)
    return lever.get("approval", NO_OWNER) if lever else NO_OWNER


def lever_owner(cfg: dict, lever_text: str) -> str:
    """Who acts, per the CONTRACT -- not per the model.

    The narrative also emits an `owner` field, and the action card used to
    render that one. It happened to agree, but a model-chosen recipient is
    the same class of mistake as a model-computed number: it is a decision,
    and decisions come from the governed contract.
    """
    lever = lever_for(cfg, lever_text)
    return lever.get("owner", NO_OWNER) if lever else NO_OWNER
