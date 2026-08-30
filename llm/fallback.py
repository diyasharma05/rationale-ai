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


def template_narrative(ctx: dict) -> dict:
    kpi, mv = ctx["kpi_name"], ctx["movement"]
    conf = ctx["confidence"]["value"]
    outcome = ctx["outcome"]
    hyps = ctx.get("hypotheses_ranked", ctx.get("hypotheses", []))
    corroborated = [h for h in hyps if h.get("snippets") or h.get("events")]
    if outcome in ("actions", "tentative") and corroborated:
        causes = "; ".join(h["label"] for h in corroborated[:3])
        body = (f"{kpi} moved: {mv}. Deterministic driver analysis plus retrieved evidence "
                f"point to: {causes}. Confidence {conf:.0%}.")
        actions = [{"driver": h["label"], "lever": l["lever"],
                    "action": f"Apply lever: {l['lever']}",
                    "expected_impact": "recover toward baseline", "owner": l["owner"],
                    "confidence": "medium", "monitoring": "weekly KPI review"}
                   for h, l in zip(corroborated, ctx.get("levers", []))]
        return {"headline": f"{kpi}: movement explained ({conf:.0%} confidence)",
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
