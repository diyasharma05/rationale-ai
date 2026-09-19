"""The reasoning pyramid : orchestrates the four escalation levels with
confidence gates between them (signal -> evidence -> action -> escalate).

Level 1  Cross-functional signals   [non-LLM]  anomaly + contribution + drivers
Level 2  Company context            [retrieval non-LLM; evidence mapping LLM]
Level 3  External signals           [non-LLM]  market-event matching
Level 4  Expert escalation          [LLM]      brief generated when gates fail

Early exit: levels stop adding cost once confidence clears the action gate
with margin (>= 0.90 after Level 2 skips Level 3).
"""
import json
import os
import re
import time

import feedback as fb
import telemetry
from llm import fallback, prompts
from llm.client import HAIKU, SONNET

from . import (anomaly, causal, confidence, contribution, db, drivers, economics,
               forecast, graph, retrieve, screening)

EARLY_EXIT = 0.90

# Confidence reported on the sparse-history path. The narrative quotes this
# constant rather than a literal, so the number shown and the number scored can
# never drift apart again (they previously read 0.25 and "limited to 0.40").
# NOTE: confidence.SPARSE_CAP is still unreachable dead code — score() is never
# called with sparse=True. That is fixed properly when confidence is recalibrated.
SPARSE_CONFIDENCE = 0.25


# kept as a module-level alias: it is referenced throughout this file and by
# the UI, which used to reach for the private name
_fmt_value = economics.fmt_value


def _movement_str(an, unit, technical: bool = True):
    """How a KPI moved, in one sentence.

    technical=True appends the standardized score — right for the analyst audit
    trail and for LLM context. technical=False is the prose form used in any
    narrative a non-analyst can see: the sanitizer drops whole sentences
    containing "z=", so a template narrative built from the technical form
    collapsed to almost nothing, and the executive persona was shown a z-score
    on the no-signal path despite the docs promising otherwise.
    """
    if an["current"] is None:
        return "no data"
    pct = an.get("pct_vs_recent") or 0.0
    # Direction and magnitude must come from the SAME comparison. This used to
    # take the direction from sign(z) (vs the long-run mean) while printing
    # |pct| (vs the trailing 3 months), so a metric that fell 7% rendered as
    # "up 7.0%" whenever the two baselines disagreed.
    d = "up" if pct > 0 else "down"
    s = (f"{_fmt_value(an['current'], unit)} in {an['period']}, {d} "
         f"{abs(pct):.1f}% vs trailing-3-month avg")
    return f"{s} (z={an.get('z')})" if technical else s


def _load_market_events():
    path = os.path.join(db.DATA, "market_events.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------- narrative sanitizer (deterministic de-slop guard) ----------------
# Whatever the LLM returns, the UI only ever shows short, human prose: sentences
# containing engine/statistics vocabulary are dropped, length is capped, and
# hypothesis-id / citation clutter is stripped from action fields.
_BANNED = ("z=", "z =", "z-score", "strength=", "share_of_delta", "share of delta",
           "evidence_gate", "action_gate", "signal=", "coverage=", "evidence=",
           "r²", "r2=", "rank-1", "rank 1 hypothesis", "driver-sourced", "conf=",
           "hypothesis (", "monitoring-only", "delta=", "current=", "baseline=",
           "co-move", "correlat")


def _clip(text, max_sentences, max_chars):
    if not text:
        return text
    parts = re.split(r"(?<=[.!?])\s+", str(text).strip())
    keep = []
    for p in parts:
        if any(b in p.lower() for b in _BANNED):
            continue
        keep.append(p)
        if len(keep) >= max_sentences or len(" ".join(keep)) >= max_chars:
            break
    out = " ".join(keep).strip()
    return out if out else str(text)[:max_chars].strip()


def _short_field(text, max_chars=110):
    t = re.sub(r"\s*\[E\d+\](\s*/\s*\[E\d+\])*", "", str(text or ""))     # strip [E#]
    t = re.sub(r"^\s*H\d+\s*[:.\-]\s*", "", t).strip()                     # strip H1:
    if len(t) > max_chars:
        t = t[:max_chars].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return t


def _tidy_narrative(n: dict) -> dict:
    n["headline"] = _clip(n.get("headline", ""), 1, 140)
    body = _clip(n.get("body", ""), 4, 520)
    # collapse citation chains like [E1][E3][E5] to the first id : full mapping
    # lives in the audit trail; prose keeps at most one cite per claim
    n["body"] = re.sub(r"(\[E\d+\])(\s*/?\s*\[E\d+\])+", r"\1", body)
    if n.get("what_could_change"):
        n["what_could_change"] = _short_field(_clip(n["what_could_change"], 1, 220), 220)
    if n.get("caveats"):
        n["caveats"] = _short_field(_clip(n["caveats"], 1, 180), 180)
    for a in n.get("actions") or []:
        a["action"] = _short_field(a.get("action"), 150)
        a["driver"] = _short_field(a.get("driver"), 90)
        a["expected_impact"] = _short_field(a.get("expected_impact"), 110)
        a["monitoring"] = _short_field(a.get("monitoring"), 110)
    return n


def _iforest_detail(f: dict) -> str:
    """Describe the ML vote without implying more evidence than there is.

    The features are 7-day rolling means, so consecutive days share six of
    seven inputs. Quoting "4 of 31 days" invites reading 31 independent
    trials; the effective sample size is nearer 31/7. The decision rule is
    also a hardcoded >10%, and here it clears by a single day -- worth stating
    plainly rather than presenting the verdict as clear-cut.
    """
    n_days, n_flag = f["n_days"], f["n_flagged"]
    ess = max(round(n_days / 7.0, 1), 1.0)
    rate = n_flag / n_days if n_days else 0.0
    # smallest count that still satisfies "rate > 10%"
    min_pass = int(0.10 * n_days) + 1
    spare = n_flag - min_pass
    fragility = ("one fewer anomalous day would flip this verdict" if spare <= 0
                 else f"{spare} day(s) to spare before the verdict flips")
    return (f"worst region {f['top_region'] or 'n/a'}: {n_flag} of {n_days} days "
            f"anomalous ({rate:.0%} vs a >10% rule). Smoothed over 7 days, so the "
            f"effective sample is about {ess} independent observations — {fragility}.")

# How much a past human correction moves a hypothesis that repeats the same
# explanation. Deliberately bounded: a correction is evidence about a past
# conclusion, not a veto over the statistics.
PRECEDENT_ADJUST = {"up": 1.15, "down": 0.6}


def _precedent_votes(kpi_id: str) -> dict:
    """driver_id -> latest human verdict on a past conclusion naming it."""
    out = {}
    try:
        for v in fb.verdicts_by_kpi(kpi_id):
            if v.get("driver"):
                out[v["driver"]] = v.get("vote")
    except Exception:
        pass          # the learning loop must never break an investigation
    return out


def _rank_hypotheses(hypotheses, driver_findings, precedent=None):
    """Objective 3: rank explanatory drivers. Strength blends statistical movement,
    unstructured corroboration and external confirmation : computed, not LLM-scored."""
    z_by_driver = {d["driver_id"]: abs(d["z"] or 0) for d in driver_findings}
    unexplained = {d["driver_id"] for d in driver_findings if d.get("unexplained")}
    for h in hypotheses:
        if h["source"] == "driver":
            stat = min(z_by_driver.get(h.get("driver_id"), 0) / 4.0, 1.0)
        elif h["source"] == "human":
            # a domain expert stating the cause outranks a model-proposed lead,
            # but it is testimony, not measurement, so it does not saturate
            stat = 0.8
        else:
            stat = 0.4
        h["strength"] = round(0.5 * stat + 0.3 * min(len(h["snippets"]) / 3.0, 1.0)
                              + 0.2 * (1.0 if h["events"] else 0.0), 2)
        # A driver that moved but that nothing upstream explains is a lead, not
        # an explanation -- it must not outrank a driver we can actually trace.
        # Without this the planted marketing tracking bug, whose |z| is the
        # largest of any driver, would lead the revenue story on sheer size.
        if h.get("driver_id") in unexplained:
            h["unexplained"] = True
            h["strength"] = round(h["strength"] * confidence.UNEXPLAINED_WEIGHT, 2)
        # The learning loop, applied where it actually changes an answer: a
        # driver a human previously marked wrong for this KPI is demoted, one
        # they confirmed is promoted.
        vote = (precedent or {}).get(h.get("driver_id"))
        if vote in PRECEDENT_ADJUST:
            h["precedent"] = vote
            h["strength"] = round(min(h["strength"] * PRECEDENT_ADJUST[vote], 1.0), 2)
    for rank, h in enumerate(sorted(hypotheses, key=lambda x: -x["strength"]), start=1):
        h["rank"] = rank
    hypotheses.sort(key=lambda x: x["rank"])


def investigate(kpi_id: str, period: str, role_id: str, llm, progress=None) -> dict:
    def _p(msg):
        if progress:
            progress(msg)

    t_start = time.perf_counter()
    contract = db.load_contract()
    cfg = contract["kpis"][kpi_id]
    roles = db.load_roles()
    persona = roles[role_id]["persona"]
    tmark = telemetry.mark()
    levels = []

    # ---------------- LEVEL 1 : cross-functional signals (non-LLM) ----------------
    _p(f"**Level 1 · Cross-functional signals** : pulling {cfg['name']} history and "
       "running the anomaly test (deterministic)…")
    t0 = time.perf_counter()
    series = db.kpi_series(kpi_id, role_id)
    an = anomaly.analyze(series, period, cfg["materiality"], cfg.get("min_history", 6))
    # Multiplicity control across everything this role monitors this month.
    # A single investigation still belongs to a family of tests -- the whole
    # portfolio is screened every period -- so the correction applies here too,
    # not just on the dashboard.
    an = screening.screen(an, kpi_id, role_id, period)
    result = {"kpi": kpi_id, "kpi_name": cfg["name"], "unit": cfg["unit"],
              "period": period, "role": role_id, "persona": persona,
              "series": series, "anomaly": an, "levels": levels,
              "hypotheses": [], "contradictions": [], "market_events": []}

    # --- sparse-history short circuit (new KPI: no causal claims) ---
    if an["sparse"]:
        levels.append({
            "level": 1, "name": "Cross-functional signals", "tag": "non-LLM",
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            "summary": f"SPARSE HISTORY : {an.get('note','')}",
            "gate": {"name": "Signal gate", "passed": False,
                     "detail": "Cannot establish a baseline; abstaining from causal claims."},
        })
        result["confidence"] = {"value": SPARSE_CONFIDENCE,
                                "components": {"signal": 0, "coverage": 0, "evidence": 0},
                                "weights": confidence.WEIGHTS, "sparse_capped": True,
                                "evidence_gate": False, "action_gate": False}
        result["outcome"] = "sparse"
        obs = series["value"].astype(float)
        band = (f"observed range so far: {_fmt_value(obs.min(), cfg['unit'])} – "
                f"{_fmt_value(obs.max(), cfg['unit'])}" if len(obs) else "no observations")
        result["narrative"] = {
            "headline": f"{cfg['name']}: too new to diagnose, so we're watching it instead",
            "body": (f"This metric is only {an['n_history']} month(s) old, and we need "
                     f"{cfg.get('min_history', 6)} before diagnosing causes. Until then we watch "
                     f"it with wider bands ({band}) and hold off on any conclusions."),
            "actions": [],
            "caveats": f"Sparse-history cap applied: confidence limited to {SPARSE_CONFIDENCE:.2f}.",
            "clarifying_question": None, "escalation_brief": None, "_fallback": False}
        result["method_mix"] = {"sql_queries": 1, "stat_tests": 1, "ml_models": 0,
                                "docs_retrieved": 0, "events_scanned": 0}
        # Log these too: no_signal and sparse are conclusions the engine
        # stands behind, and they were 20 of 24 eval cases never reaching the
        # ledger at all -- so "every investigation is appended here" was false.
        result["inv_id"] = fb.log_investigation(result)
        result["telemetry"] = telemetry.slice_from(tmark)
        result["wall_ms"] = round((time.perf_counter() - t_start) * 1000, 1)
        return result

    # --- signal gate: is this alert really abnormal? ---
    if not an["material"]:
        levels.append({
            "level": 1, "name": "Cross-functional signals", "tag": "non-LLM",
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            "summary": _movement_str(an, cfg["unit"]),
            "gate": {"name": "Signal gate", "passed": False,
                     "detail": (
                         (f"Cleared this KPI's own bar (z={an['z']}, Δ={an['pct_vs_recent']}%) "
                          f"but not multiplicity control across the {an.get('family_size', 0)} KPIs "
                          f"screened this month: q={an.get('q_value')} at FDR {screening.FDR_Q}. "
                          "Expected to be a false alarm, so no investigation opened.")
                         if an.get("fdr_suppressed") else
                         (f"Within normal variation: needs |z|≥{cfg['materiality']['min_abs_z']} "
                          f"and |Δ%|≥{cfg['materiality']['min_pct']} "
                          f"(got z={an['z']}, Δ={an['pct_vs_recent']}%). No investigation opened : "
                          "this is the noise filter that prevents alert fatigue."))},
        })
        result["confidence"] = confidence.score(an["z"], [], [])
        result["outcome"] = "no_signal"
        # the forward view and the contract's blast radius are worth having
        # even when nothing moved: they are what "normal" looks like next month
        result["forecast"] = forecast.next_months(series, an, cfg["unit"])
        result["exposure"] = graph.exposure(contract, kpi_id)
        result["narrative"] = {
            "headline": f"{cfg['name']}: nothing unusual here",
            "body": (f"{_movement_str(an, cfg['unit'], technical=False)}. "
                     + ("Across every metric watched this month, a movement this size is "
                        "the kind that turns up by chance, so no investigation was opened."
                        if an.get("fdr_suppressed") else
                        "That's inside this metric's normal range, so no investigation was "
                        "opened : this is the filter that keeps the team from chasing noise.")),
            "actions": [], "caveats": None, "clarifying_question": None,
            "escalation_brief": None, "_fallback": False}
        result["method_mix"] = {"sql_queries": 1, "stat_tests": 2, "ml_models": 0,
                                "docs_retrieved": 0, "events_scanned": 0}
        result["inv_id"] = fb.log_investigation(result)
        result["telemetry"] = telemetry.slice_from(tmark)
        result["wall_ms"] = round((time.perf_counter() - t_start) * 1000, 1)
        return result

    _p(f"Signal gate **passed** (z={an['z']}, Δ{an['pct_vs_recent']}%) : breaking the "
       "movement down by region, segment and category, then checking the contract's drivers…")
    contrib = contribution.top_contributors(kpi_id, cfg, period, role_id)
    driver_findings = drivers.check_drivers(cfg, an["z"], period, role_id,
                                            parent_series=series)
    # Three things the brief's solutioning areas name that sit beside the
    # verdict without touching the confidence score or the gates: a causal
    # estimate (difference-in-differences, identifiable only when an untreated
    # comparison group exists), a forward view stated with its width, and the
    # contract's blast radius (who else this movement touches).
    causal_est = causal.estimate(kpi_id, period, role_id, contrib["focus_regions"], an)
    fc = forecast.next_months(series, an, cfg["unit"])
    exposure = graph.exposure(contract, kpi_id)

    # --- corroborating detectors (all non-LLM) ---
    # Deliberately NOT called an ensemble of independent votes. The OLS check
    # is fit on the SAME history as the z-test, with the same residual scale,
    # so it agrees with it on essentially every case (measured r-squared < 0.06
    # -- the "trend" it extrapolates explains almost none of the variance). It
    # is a consistency check, not a second opinion. Only the IsolationForest,
    # which works at daily grain per region, sees anything the monthly test
    # cannot.
    votes = [{"detector": "z-score + materiality (statistics)",
              "flag": bool(an["material"]),
              "detail": f"z={an['z']} vs gate ±{cfg['materiality']['min_abs_z']}, "
                        f"Δ={an['pct_vs_recent']}% vs ±{cfg['materiality']['min_pct']}%"}]
    fchk = an.get("forecast_check")
    if fchk:
        def _n(v):  # compact number, unit stated once in the sentence
            return f"₹{v/1e5:.1f}L" if cfg["unit"].startswith("INR") else f"{v:,.1f}"
        votes.append({"detector": "OLS trend forecast (regression, 90% interval; same history as the z-test, so not independent)",
                      "flag": bool(fchk["outside"]),
                      "detail": (f"actual {_n(an['current'])} vs expected "
                                 f"{_n(fchk['lo'])}–{_n(fchk['hi'])}")})
    iforest = None
    if cfg.get("ml_daily_check"):
        try:
            from . import stats_ml
            iforest = stats_ml.iforest_daily(db.revenue_daily(role_id), period)
        except Exception as e:
            print(f"[ml] iforest skipped: {e}")
        if iforest:
            votes.append({"detector": "IsolationForest per region, daily grain (ML)",
                          "flag": bool(iforest["flagged"]),
                          "detail": _iforest_detail(iforest)})
    hypotheses = []
    for d in driver_findings:
        if d["status"] == "co_moves":
            hid = f"H{len(hypotheses)+1}"
            hypotheses.append({
                "id": hid, "source": "driver", "driver_id": d["driver_id"],
                # Prose label (no "z="): it is joined into the offline template
                # narrative, which the sanitizer would otherwise discard, and it
                # is rendered to every persona in the UI. Direction and magnitude
                # both come from the mean-baseline that decided `status`.
                "label": (f"{d['label']} moved {'up' if d['z'] > 0 else 'down'} "
                          f"{abs(d['pct_vs_mean'] or 0):.1f}% : {d['note']}"),
                "label_technical": (f"{d['label']} moved {'up' if d['z'] > 0 else 'down'} "
                                    f"{abs(d['pct_vs_mean'] or 0):.1f}% (z={d['z']:.1f}) : "
                                    f"{d['note']}"),
                "keywords": d["tags"] + [r.lower() for r in contrib["focus_regions"]],
                "snippets": [], "events": [], "key_facts": [],
            })
    contradictions = [d for d in driver_findings if d["status"] == "contradicts"]
    conf1 = confidence.score(an["z"], driver_findings, hypotheses)
    levels.append({
        "level": 1, "name": "Cross-functional signals",
        "tag": "non-LLM: SQL + statistics + ML",
        "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
        "summary": _movement_str(an, cfg["unit"]),
        "sql": db.kpi_sql(kpi_id, role_id),
        "votes": votes,
        "contribution": {k: v.head(6) for k, v in contrib["tables"].items()},
        "focus_regions": contrib["focus_regions"],
        "drivers": driver_findings,
        "causal": causal_est,
        "forecast": fc,
        "confidence_after": conf1["value"],
        "gate": {"name": "Signal gate", "passed": True,
                 "detail": (f"z={an['z']} (needs ≥{cfg['materiality']['min_abs_z']}), "
                            f"Δ={an['pct_vs_recent']}% (needs ≥{cfg['materiality']['min_pct']}%)"
                            + (f", business impact ≈ "
                               f"{economics.fmt_value(economics.monthly_impact(an, cfg['unit']), 'INR')}/month"
                               if economics.monthly_impact(an, cfg['unit']) is not None else "")
                            + ". Focus: " + (", ".join(contrib["focus_regions"])
                               or "no regional concentration (movement is spread evenly, "
                                  "which points away from a regional cause)"))},
    })
    result.update(hypotheses=hypotheses, contradictions=contradictions,
                  contribution=contrib, drivers=driver_findings,
                  causal=causal_est, forecast=fc, exposure=exposure)

    # ---------------- LEVEL 2 : company context (retrieval + LLM mapping) ----------------
    _p("**Level 2 · Company context** : searching tickets, transcripts, ops notes and the "
       "decision ledger; Claude maps what actually supports each hypothesis…")
    t0 = time.perf_counter()
    ret = retrieve.search(cfg, contrib["focus_regions"], driver_findings, role_id,
                          exclude_kpi=kpi_id, exclude_period=period)
    # fixtures tell July-2026's story; any other analysis month must never replay
    # them : it falls through to live calls or the deterministic template
    fsuf = "" if period == "2026-07" else f"_{period}"
    extract = None
    if ret["snippets"]:
        extract = llm.json_call(
            f"extract_{kpi_id}{fsuf}", prompts.EXTRACT_SYSTEM,
            prompts.build_extract_prompt(cfg["name"], _movement_str(an, cfg["unit"]),
                                         hypotheses, ret["snippets"]),
            model=HAIKU, max_tokens=1500)
    if extract is None:
        extract = fallback.heuristic_extract(hypotheses, ret["snippets"])
    nh = extract.get("new_hypothesis")
    unvalidated_lead, nh_obj = None, None
    if nh:
        # Hallucination guard: an LLM-proposed hypothesis is only admitted when the
        # contract declares NO causal drivers for this KPI (nothing structured to
        # check against). If declared drivers exist but stayed quiet/contradicting,
        # an unstructured anecdote must not rescue confidence : it is surfaced as an
        # unvalidated lead instead of evidence.
        if not cfg.get("drivers"):
            nh_obj = {"id": f"H{len(hypotheses)+1}", "source": "unstructured",
                      "label": re.sub(r"^\s*H\d+\s*[:.\-]\s*", "", nh["label"]),
                      "keywords": nh.get("keywords", []),
                      "snippets": [], "events": [], "key_facts": []}
            hypotheses.append(nh_obj)
        else:
            unvalidated_lead = nh["label"]
    result["unvalidated_lead"] = unvalidated_lead
    # Admit the new hypothesis BEFORE applying mappings: an extract for a driverless
    # KPI labels its own hypothesis (e.g. "H1"), so unknown support ids resolve to it
    # instead of being silently dropped.
    by_id = {h["id"]: h for h in hypotheses}
    for m in extract.get("mappings", []):
        for hid in m.get("supports", []):
            target = by_id.get(hid) or nh_obj
            if target and m["snippet_id"] not in target["snippets"]:
                target["snippets"].append(m["snippet_id"])
                if m.get("key_fact"):
                    target["key_facts"].append(f"[{m['snippet_id']}] {m['key_fact']}")
    # extracts for driverless KPIs sometimes mark documents relevant without any
    # supports ids : those back the (only) new hypothesis, so attach them there
    if nh_obj and not nh_obj["snippets"]:
        for m in extract.get("mappings", []):
            if m.get("relevant") and not m.get("supports"):
                nh_obj["snippets"].append(m["snippet_id"])
                if m.get("key_fact"):
                    nh_obj["key_facts"].append(f"[{m['snippet_id']}] {m['key_fact']}")
    # ---- the abstain loop closes here ----
    # When the engine abstained earlier it asked a human a specific question.
    # If a human has since answered, that answer is evidence with HUMAN
    # provenance. A confirmed cause becomes a hypothesis with source="human";
    # the hallucination guard above does not apply to it, because the guard
    # exists to stop the MODEL inventing causes -- a domain expert stating one
    # is exactly the input the contract cannot encode. A ruled-out cause is
    # recorded so the narrative can say it was checked, by whom.
    human_answers = fb.answers_for(kpi_id, period)
    answer_snips = [s["id"] for s in ret["snippets"] if s.get("kind") == "human_answer"]
    eliminated_leads = []
    for a in human_answers:
        if a.get("confirms") is True:
            hypotheses.append({
                "id": f"H{len(hypotheses)+1}", "source": "human",
                "label": str(a.get("answer", "")).strip()[:160],
                "actor": a.get("actor"), "keywords": [],
                "snippets": list(answer_snips), "events": [],
                "key_facts": [f"[{sid}] {a.get('answer', '')[:120]}" for sid in answer_snips],
            })
        elif a.get("confirms") is False:
            eliminated_leads.append({"lead": str(a.get("answer", "")).strip()[:160],
                                     "actor": a.get("actor")})
    result["eliminated_leads"] = eliminated_leads
    result["human_answers"] = len(human_answers)

    conf2 = confidence.score(an["z"], driver_findings, hypotheses)
    corroborated = sum(1 for h in hypotheses if h["snippets"])
    levels.append({
        "level": 2, "name": "Company context (unstructured + decision ledger)",
        "tag": "retrieval: non-LLM · evidence mapping: LLM (Haiku)"
              + (" : heuristic fallback" if extract.get("_fallback") else ""),
        "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
        "summary": (f"{len(ret['snippets'])} of {ret['corpus_size']} documents retrieved; "
                    f"{corroborated}/{len(hypotheses)} hypotheses corroborated"),
        "snippets": ret["snippets"], "query_terms": ret["terms"], "mappings": extract.get("mappings", []),   # live JSON may omit it entirely
        "confidence_after": conf2["value"],
        "gate": None,
    })
    result["snippets"] = ret["snippets"]

    # ---------------- LEVEL 3 : external signals (non-LLM matching) ----------------
    if conf2["value"] < EARLY_EXIT:
        _p("**Level 3 · External signals** : matching competitor / industry / macro events "
           "to the focus regions and hypotheses…")
        t0 = time.perf_counter()
        matched = []
        all_kw = set(t.lower() for t in cfg.get("tags", []))
        for h in hypotheses:
            all_kw |= set(k.lower() for k in h["keywords"])
        for ev in _load_market_events():
            region_ok = (not ev["regions"]) or bool(set(ev["regions"]) & set(contrib["focus_regions"]))
            tag_hits = set(t.lower() for t in ev["tags"]) & all_kw
            if region_ok and tag_hits:
                matched.append(ev)
                attached = False
                for h in hypotheses:
                    if set(t.lower() for t in ev["tags"]) & set(k.lower() for k in h["keywords"]):
                        h["events"].append(ev["headline"])
                        attached = True
                if not attached:
                    hypotheses.append({"id": f"H{len(hypotheses)+1}", "source": "external",
                                       "label": f"External: {ev['headline']}",
                                       "keywords": ev["tags"], "snippets": [],
                                       "events": [ev["headline"]], "key_facts": []})
        conf3 = confidence.score(an["z"], driver_findings, hypotheses)
        levels.append({
            "level": 3, "name": "External signals (industry / competitor / macro)",
            "tag": "non-LLM (tag + region matching over event feed)",
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            "summary": f"{len(matched)} market event(s) matched to this investigation",
            "events": matched, "confidence_after": conf3["value"], "gate": None,
        })
        result["market_events"] = matched
        final_conf = conf3
    else:
        levels.append({"level": 3, "name": "External signals : SKIPPED (early exit)",
                       "tag": "non-LLM", "duration_ms": 0.0,
                       "summary": f"Confidence {conf2['value']:.2f} ≥ {EARLY_EXIT} after Level 2; "
                                  "pyramid exits early to save latency and cost.",
                       "events": [], "confidence_after": conf2["value"], "gate": None})
        final_conf = conf2

    # ---------------- rank drivers + gates -> outcome ----------------
    _rank_hypotheses(hypotheses, driver_findings, _precedent_votes(kpi_id))
    result["confidence"] = final_conf
    if final_conf["action_gate"]:
        outcome = "actions"
    elif final_conf["evidence_gate"]:
        outcome = "tentative"
    else:
        outcome = "abstain"
    result["outcome"] = outcome
    levels.append({
        "level": "G", "name": "Confidence gates", "tag": "non-LLM",
        "duration_ms": 0.0,
        "summary": (f"score {final_conf['value']:.2f} : evidence gate "
                    f"{'PASSED' if final_conf['evidence_gate'] else 'FAILED'} (≥{confidence.EVIDENCE_GATE}), "
                    f"action gate {'PASSED' if final_conf['action_gate'] else 'FAILED'} "
                    f"(≥{confidence.ACTION_GATE}) → outcome: {outcome.upper()}"),
        "gate": {"name": "Evidence + Action gates",
                 "passed": final_conf["evidence_gate"],
                 "detail": f"components: {final_conf['components']} weights: {confidence.WEIGHTS}"},
    })

    # ---------------- narrative (LLM) + LEVEL 4 when abstaining ----------------
    # A human answer changes the facts, so it must not replay the fixture
    # recorded for the unanswered investigation (which may be abstain prose).
    # Distinct key: falls back to the deterministic template offline.
    _ans = "_answered" if human_answers else ""
    ctx = {
        "kpi_name": cfg["name"], "unit": cfg["unit"], "period": period,
        # prose form: this string is both the LLM's grounding sentence (the
        # prompt bans statistics vocabulary anyway) and the opening clause of
        # the offline template narrative, which the sanitizer would otherwise
        # discard wholesale for containing "z=".
        "movement": _movement_str(an, cfg["unit"], technical=False),
        "rupee_impact": (f'{economics.fmt_value(_impact, "INR")} per month (approx)'
                         if (_impact := economics.monthly_impact(an, cfg["unit"])) is not None
                         else None),
        "focus_regions": contrib["focus_regions"],
        # "diffuse" is a real finding, not a missing value: a movement spread
        # evenly across every region argues against a regional cause and
        # towards something systemic, such as a measurement change.
        "regional_concentration": contrib.get("concentration"),
        "contributions_are_additive": contrib.get("additive"),
        "top_contributions": {dim: {"values_unit": cfg.get("dim_unit", cfg["unit"]),
                                    "rows": t.head(4).to_dict("records")}
                              for dim, t in contrib["tables"].items()},
        "hypotheses_ranked": [{k: h.get(k) for k in ("rank", "strength", "id", "source", "unexplained", "actor",
                                                     "label", "snippets", "events", "key_facts")}
                              for h in hypotheses],
        "contradicting_drivers": [
            {"label": d["label"], "z": d["z"], "pct": d["pct"], "relation": d["relation"],
             "note": f"moved {'up' if d['z']>0 else 'down'} : the opposite of what would explain the KPI"}
            for d in contradictions],
        "confidence": final_conf, "outcome": outcome,
        "unvalidated_lead": unvalidated_lead,
        "detector_ensemble": [{"detector": v["detector"], "flag": v["flag"]} for v in votes],
        "driver_comovement_r_12m_incl_current": {
            d["label"]: d["corr"] for d in driver_findings if d.get("corr") is not None},
        "levers": cfg.get("levers", []),
        "past_playbooks": [s["text"][:300] for s in ret["snippets"] if s["kind"] == "ledger"],
        # computed, never model-scored; the prompt may quote them once, with the assumption
        "causal_estimate": ({"identifiable": True, "summary": causal.summary_line(causal_est),
                             "treated": causal_est["treated"], "controls": causal_est["controls"],
                             "effect": causal_est["effect"], "ci95": causal_est["ci95"],
                             "unit": causal_est["unit"],
                             "parallel_trends_ok": causal_est["pretrend"]["parallel_ok"],
                             "monthly_effect": causal_est.get("monthly_effect"),
                             "share_of_movement": causal_est.get("share_of_movement")}
                            if causal_est.get("identifiable") else
                            {"identifiable": False, "reason": causal_est.get("reason")}),
        "forecast": ({"summary": forecast.summary_line(fc, economics.fmt_value),
                      "periods": fc["periods"], "pred": fc["pred"], "lo": fc["lo"], "hi": fc["hi"],
                      "r2": fc["r2"]} if fc else None),
        "downstream_exposure": exposure,
    }
    _p("**Narrative** : writing the persona-specific explanation and grounded actions "
       "(Claude Sonnet, numbers passed in verbatim)…")
    ctx_masked = json.loads(db.mask_text(json.dumps(ctx, default=str), role_id))
    style = roles[role_id].get("narrative_style", "")
    # max_tokens generous (adaptive thinking counts against the cap); low effort
    # keeps live-demo latency down : the analysis is already done upstream
    narrative = llm.json_call(f"narrative_{kpi_id}_{persona}{fsuf}{_ans}", prompts.NARRATIVE_SYSTEM,
                              prompts.build_narrative_prompt(ctx_masked, persona, style),
                              model=SONNET, max_tokens=8000, effort="low")
    if narrative is None:
        narrative = fallback.template_narrative({**ctx_masked, "kpi_name": cfg["name"]})
    narrative = _tidy_narrative(narrative)
    narrative["headline"] = db.mask_text(narrative.get("headline", ""), role_id)
    narrative["body"] = db.mask_text(narrative.get("body", ""), role_id)
    result["narrative"] = narrative
    if outcome == "abstain":
        levels.append({
            "level": 4, "name": "Expert escalation (brief prepared)",
            "tag": "LLM (Sonnet)", "duration_ms": 0.0,
            "summary": "Confidence below evidence gate : a human-expert escalation brief was "
                       "generated instead of a root-cause claim.",
            "gate": {"name": "Escalate", "passed": True,
                     "detail": narrative.get("escalation_brief") or "brief in narrative"},
        })

    # what built this answer : operation counts by method (rendered in the UI so
    # the LLM/non-LLM split is visible at a glance, not buried in expanders)
    result["method_mix"] = {
        "sql_queries": 1 + 4 * len(cfg.get("dimensions", [])) + len(driver_findings)
                       + (1 if iforest else 0),
        "stat_tests": 2 + 2 * len(driver_findings)
                      + (3 if causal_est.get("identifiable") else 0),   # DiD, pre-trend placebo, permutation
        "ml_models": (iforest or {}).get("n_models", 0),
        "docs_retrieved": len(ret["snippets"]),
        "events_scanned": len(_load_market_events()),
    }
    result["telemetry"] = telemetry.slice_from(tmark)
    result["wall_ms"] = round((time.perf_counter() - t_start) * 1000, 1)
    result["inv_id"] = fb.log_investigation(result)
    try:                       # Prometheus mirror (no-op if not installed)
        import metrics
        metrics.record_investigation(result)
    except Exception:
        pass
    return result
