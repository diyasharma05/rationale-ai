"""Plain-English question -> governed KPI.

Deterministic keyword scoring first, with an optional model fallback for
phrasing the keywords miss. Both halves live here: the LLM half used to be
inlined in the page body, where it could not be tested at all.
"""
import re

SYNONYMS = {"sales": "revenue", "money": "revenue", "income": "revenue",
            "deliveries": "delivery", "shipping": "delivery", "late": "sla",
            "clients": "accounts", "customers": "customer", "churn": "churn",
            "ads": "marketing", "leads": "conversion", "basket": "basket"}

NAME_WEIGHT = 3      # a KPI's own name is stronger evidence than a topic tag
TAG_WEIGHT = 1


def match_kpi(question: str, kpis: dict):
    """Returns (kpi_id, how) or (None, None).

    Requires a strictly unique maximum: an ambiguous question ("is our delivery
    promise slipping?" matches three KPIs) should ask rather than guess.
    """
    toks = [SYNONYMS.get(t, t) for t in re.findall(r"[a-z]+", question.lower())]
    scores = {}
    for kpi_id, cfg in kpis.items():
        name_toks = set(re.findall(r"[a-z]+", cfg["name"].lower()))
        tag_toks = {t.lower() for t in cfg.get("tags", [])}
        scores[kpi_id] = (sum(NAME_WEIGHT for t in toks if t in name_toks)
                          + sum(TAG_WEIGHT for t in toks if t in tag_toks))
    if not scores:
        return None, None
    best = max(scores, key=scores.get)
    ranked = sorted(scores.values(), reverse=True)
    if scores[best] > 0 and (len(ranked) < 2 or ranked[0] > ranked[1]):
        return best, "keyword match"
    return None, None


def resolve(question: str, kpis: dict, llm=None):
    """Keyword match, then an optional model fallback.

    The fallback is live-only by design: in mock mode there is no fixture for
    an arbitrary question, so a miss must surface as "I could not map that"
    rather than silently replaying an unrelated cached answer.
    """
    matched, how = match_kpi(question, kpis)
    if matched or llm is None or getattr(llm, "mode", "mock") != "live":
        return matched, how

    from llm import prompts
    from llm.client import HAIKU
    data = llm.json_call(
        "intent", prompts.INTENT_SYSTEM,
        f"KPIs: {[(k, kpis[k]['name']) for k in kpis]}\nQuestion: {question}",
        model=HAIKU, max_tokens=300)
    if data and data.get("kpi_id") in kpis:
        return data["kpi_id"], "Claude intent"
    return None, None
