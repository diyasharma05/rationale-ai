"""Deterministic fallbacks used when no LLM is available and no fixture exists
for a task. Keeps every investigation path demo-safe offline.
"""


def heuristic_extract(hypotheses: list, snippets: list) -> dict:
    """Keyword-overlap evidence mapping (>=2 keyword hits => support)."""
    mappings = []
    for s in snippets:
        low = s["text"].lower()
        supports = []
        for h in hypotheses:
            hits = sum(1 for kw in h.get("keywords", []) if kw.lower() in low)
            if hits >= 2:
                supports.append(h["id"])
        mappings.append({
            "snippet_id": s["id"], "relevant": bool(supports), "supports": supports,
            "key_fact": s["text"].splitlines()[0][:140] if supports else "",
        })
    return {"mappings": mappings, "new_hypothesis": None, "_fallback": True}


def _strip_yes_no(text):
    """Answers are typed as replies ("Yes - a tag change shipped..."); in prose
    the leading yes/no is noise."""
    import re
    t = re.sub(r"^\s*(yes|no)\s*[—–\-:,.]*\s*", "", str(text), flags=re.I).strip()
    return t or str(text)


def template_narrative(ctx: dict) -> dict:
    kpi, mv = ctx["kpi_name"], ctx["movement"]
    conf = ctx["confidence"]["value"]
    outcome = ctx["outcome"]
    hyps = ctx.get("hypotheses_ranked", ctx.get("hypotheses", []))
    corroborated = [h for h in hyps if h.get("snippets") or h.get("events")]
    if outcome in ("actions", "tentative") and corroborated:
        # A human-stated cause is testimony, not analysis. Say who said it and
        # do not dress it up as something the engine derived.
        human = [h for h in corroborated if h.get("source") == "human"]
        derived = [h for h in corroborated if h.get("source") != "human"]
        parts = []
        if human:
            who = ", ".join(sorted({str(h.get("actor") or "a colleague") for h in human}))
            said = "; ".join(_strip_yes_no(h["label"]) for h in human[:2])
            parts.append(f"confirmed by {who}: {said}")
        if derived:
            parts.append("driver analysis plus retrieved evidence point to: "
                         + "; ".join(h["label"] for h in derived[:3]))
        verdict_word = "likely explained" if outcome == "tentative" else "explained"
        sentences = ". ".join(s[0].upper() + s[1:] for s in parts)
        body = f"{kpi} moved: {mv}. {sentences}. Confidence {conf:.0%}."
        actions = [{"driver": h["label"], "lever": l["lever"],
                    "action": f"Apply lever: {l['lever']}",
                    "expected_impact": "recover toward baseline", "owner": l["owner"],
                    "confidence": "medium", "monitoring": "weekly KPI review"}
                   for h, l in zip(derived, ctx.get("levers", []))]
        return {"headline": f"{kpi}: movement {verdict_word} ({conf:.0%} confidence)",
                "body": body, "actions": actions if outcome == "actions" else [],
                "what_could_change": "Contradicting driver data or new evidence against the "
                                     "ranked causes would lower this conclusion's confidence.",
                "caveats": "Template narrative (offline fallback).",
                "clarifying_question": None, "escalation_brief": None, "_fallback": True}
    return {"headline": f"{kpi}: insufficient evidence, abstaining",
            "body": (f"{kpi} moved ({mv}) but the evidence gate failed at confidence "
                     f"{conf:.0%}. No corroborated cause; the engine abstains rather than "
                     "guess."),
            "actions": [],
            "what_could_change": "A confirmed upstream cause (e.g. a tracking or process "
                                 "change) would let the engine re-open this with evidence.",
            "caveats": "Template narrative (offline fallback).",
            "clarifying_question": "Did any measurement/tracking or process change occur "
                                   "in this period that could explain the movement?",
            "escalation_brief": f"Escalation: {kpi} moved {mv}; automated diagnosis "
                                "abstained. Requesting human review.",
            "_fallback": True}

def kpi_one_liner(cfg: dict, an: dict) -> str:
    """One plain-English sentence about a KPI : templated from the numbers,
    no LLM. Peer of template_narrative, and lives here for the same reason:
    deterministic prose belongs with the other deterministic prose, not in
    the view layer.

    Direction and magnitude both come from the trailing-3 comparison. The
    earlier version in app.py read the direction off sign(z) (vs the long-run
    mean) while printing the percentage vs the trailing 3 months, so a metric
    that fell could be described as having risen.
    """
    from engine import economics

    name = cfg["name"].split(" (")[0]
    if an["sparse"]:
        return (f"{name} is new : only {an['n_history']} month(s) of history so far, "
                f"so we're watching it rather than judging it.")
    val = economics.fmt_value(an["current"], cfg["unit"])
    usual = economics.fmt_value(an["mean"], cfg["unit"])
    pct = an.get("pct_vs_recent") or 0.0
    direction = "up" if pct > 0 else "down"
    if an["material"]:
        imp = economics.monthly_impact(an, cfg["unit"])
        tail = (f" If it holds, that's about {economics.fmt_value(imp, 'INR')} a month."
                if imp is not None else "")
        return (f"{name} came in at {val} : {direction} about "
                f"{abs(pct):.0f}% from its usual {usual}. That's well outside "
                f"its normal range, which is why it's flagged.{tail}")
    return (f"{name} is at {val}, close to its usual {usual} : moving around, "
            "but nothing unusual.")
