"""How the answer was built: methods, cost, accuracy, contract, security."""
import json as _json
import os
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml

import feedback as fb
import telemetry
from engine import (anomaly, confidence, db, economics, explore, policy,
                    pyramid, screening, stats_ml, stream)
from llm import prompts

DATA_DIR = db.DATA      # was an app.py global
from services import intent as intent_service
from services import scan as scan_service
from ui.common import (C, pd, stat_tile)


def render(ctx):
    """Entry point. Page-local names are unpacked from ctx here so the
    body below stays exactly as it rendered before the split -- the
    snapshots prove it, and it keeps this a move rather than a rewrite.
    """
    role_id = ctx.viewer.role_id
    persona = ctx.viewer.persona
    is_exec = ctx.viewer.is_exec
    roles = db.load_roles()
    PERIOD = ctx.window.period
    llm = ctx.llm
    _ = (role_id, persona, is_exec, roles, PERIOD, llm)   # some pages use a subset

    st.header("Under the Hood")

    st.subheader("LLM vs non-LLM breakdown")
    st.caption("Judged requirement: the LLM is never the source of quantitative truth.")
    st.dataframe(pd.DataFrame([
        {"step": "KPI series & aggregations", "type": "SQL (DuckDB, from the semantic contract)", "model": "—",
         "why": "The contract's SQL is executed verbatim, with the RBAC WHERE clause injected : shown in every investigation"},
        {"step": "Signal gate detector 1: z-score + materiality", "type": "Statistics (numpy)", "model": "—",
         "why": "Statistics decide abnormality; reproducible and auditable"},
        {"step": "Signal gate detector 2: OLS trend forecast, 90% prediction interval", "type": "Regression (numpy)", "model": "—",
         "why": "A second, independent test: is the actual outside what the trend predicted?"},
        {"step": "Signal gate detector 3: IsolationForest at daily grain", "type": "Machine learning (scikit-learn)", "model": "—",
         "why": "Trained on the trailing year of daily revenue; catches day-level anomalies monthly tests smooth over"},
        {"step": "3-month KPI forecasts on every trend panel", "type": "Regression (OLS + PI)", "model": "—",
         "why": "Projects the trajectory if nothing is done : the 'cost of inaction'"},
        {"step": "Contribution analysis (region/segment/category)", "type": "SQL (DuckDB)", "model": "—",
         "why": "Additive decomposition is arithmetic, not language"},
        {"step": "Driver check: concurrency + Pearson co-movement of MoM changes", "type": "SQL + statistics", "model": "—",
         "why": "Causal links come from the governed contract; movement and co-movement are measured, evidence corroborates"},
        {"step": "Unstructured retrieval (tickets, transcripts, ledger)", "type": "Deterministic (weighted keyword TF)", "model": "—",
         "why": "Transparent, stable ranking; embeddings are a roadmap upgrade"},
        {"step": "Evidence mapping (snippet → hypothesis)", "type": "LLM", "model": "claude-haiku-4-5",
         "why": "Reading language is the LLM's job; the mapping is then COUNTED in Python"},
        {"step": "External event matching", "type": "Deterministic (tag/region match)", "model": "—",
         "why": "Structured event feed needs no language model"},
        {"step": "Confidence score & gates", "type": "Deterministic (weighted formula)", "model": "—",
         "why": "Score arithmetic must be reproducible to be trusted"},
        {"step": "Question → KPI intent", "type": "Hybrid (keywords first, LLM fallback)", "model": "claude-haiku-4-5",
         "why": "Cheap deterministic path covers most phrasings; LLM handles the rest"},
        {"step": "Persona narrative, actions text, escalation brief", "type": "LLM", "model": "claude-sonnet-5",
         "why": "Language synthesis over precomputed facts, with numbers passed in verbatim"},
    ]), hide_index=True, width="stretch")

    st.subheader("Latency, cost & scalability")
    inv = list(st.session_state.investigations.values())
    if inv:
        lat = pd.DataFrame([{"investigation": f"{x['kpi_name']} ({x['role']})",
                             "outcome": x["outcome"],
                             "end-to-end (s)": round(x.get("wall_ms", 0) / 1000, 2),
                             "LLM calls": len(x.get("telemetry", []))} for x in inv])
        st.dataframe(lat, hide_index=True)
    st.markdown("""
    - **Latency budget**: interactive target < 20 s live, < 2 s mock. Deterministic analytics run in
      milliseconds (DuckDB pushdown); LLM narrative dominates and runs at `effort=low`.
    - **Cost control**: prompts carry only precomputed aggregates (never raw tables); Haiku for
      mapping, Sonnet only for prose; per-insight cost ≈ ₹1–3. Session-level caching means a
      re-viewed investigation costs zero.
    - **Scalability**: each investigation is stateless given (KPI, period, role) : horizontally
      shardable; fixtures + deterministic fallbacks make the system degrade gracefully, never fail.
    """)

    st.subheader("Does it actually get the right answer?")
    st.caption("The generator plants known causes, so we have ground truth. This is the "
               "engine scored against it across an incident month and three control "
               "months — regenerate any time with `python eval.py`.")
    _ev_path = os.path.join(DATA_DIR, "eval_results.json")
    if not os.path.exists(_ev_path):        # legacy location
        _ev_path = os.path.join(DATA_DIR, "state", "eval_results.json")
    ev = None
    if os.path.exists(_ev_path):
        import json as _json
        try:
            with open(_ev_path, encoding="utf-8") as _f:
                ev = _json.load(_f)
        except Exception as e:
            ev = None
            st.warning(f"Could not read evaluation results: {e}")
    if ev:
        d, rc, ab, fa = (ev["detection"], ev["root_cause"], ev["abstention"],
                         ev.get("false_alarm_impact", {}))
        e1, e2, e3, e4 = st.columns(4)
        e1.markdown(stat_tile("Detection recall", f"{d['recall']:.0%}",
                              chip=f"precision {d['precision']:.0%}",
                              sub=f"TP {d['tp']} · FP {d['fp']} · FN {d['fn']} · TN {d['tn']}",
                              accent=C["good"]), unsafe_allow_html=True)
        e2.markdown(stat_tile("Root-cause accuracy",
                              f"{rc['accuracy']:.0%}" if rc["accuracy"] is not None else "—",
                              sub=f"{rc['hits']} of {rc['total']} planted causes identified",
                              accent=C["good"]), unsafe_allow_html=True)
        e3.markdown(stat_tile("Abstention", f"{ab['correct']}/{ab['expected']}",
                              sub=f"{ab['false_abstentions']} false abstentions",
                              accent=C["good"]), unsafe_allow_html=True)
        e4.markdown(stat_tile("False alarms", f"{fa.get('harmful', 0)} harmful",
                              chip=f"{fa.get('contained', 0)} contained",
                              sub="contained = flagged, then the gate refused a cause",
                              accent=C["warning"] if fa.get("contained") else C["good"]),
                    unsafe_allow_html=True)
        st.markdown("**Confidence calibration** — do high-confidence answers turn out correct?")
        st.dataframe(pd.DataFrame(ev["calibration"]), hide_index=True, width="stretch")
        with st.expander(f"All {len(ev['cases'])} evaluated cases"):
            cdf = pd.DataFrame(ev["cases"])
            cdf["result"] = cdf["correct"].map({True: "correct", False: "MISS", None: "—"})
            st.dataframe(cdf[["period", "kpi_name", "outcome", "confidence", "result", "note"]],
                         hide_index=True, width="stretch", height=340)
        st.caption(f"Run {ev['generated_at']} · median {ev['runtime']['median_ms']:.0f} ms "
                   f"per investigation · {ev['runtime']['mean_llm_calls']} LLM calls each. "
                   "Scored against synthetic ground truth — it validates the engine's logic, "
                   "not real-world accuracy, which needs a client's labelled history.")
    else:
        st.info("No evaluation results yet — run `python eval.py` to generate them.")

    st.subheader("Cumulative session telemetry")
    # Only this session's calls. telemetry.RECORDS is process-global and shared
    # across browser sessions, so reading it directly showed other visitors'
    # activity in a panel captioned "session telemetry".
    session_calls = telemetry.slice_from(st.session_state.get("_tel_start", 0))
    if session_calls:
        st.dataframe(pd.DataFrame(session_calls)[["task", "model", "mode", "latency_ms",
                                                  "input_tokens", "output_tokens", "cost_usd", "cost_inr"]],
                     hide_index=True, height=260)
        s = telemetry.summarize(session_calls)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("LLM calls", s["llm_calls"])
        k2.metric("Tokens (in + out)", f"{s['input_tokens']:,} + {s['output_tokens']:,}")
        k3.metric("Cost", f"${s['cost_usd']}")
        k4.metric("Cost (INR)", f"₹{s['cost_inr']}")
        st.caption("Pricing: Haiku 4.5 $1/$5 · Sonnet 5 $2/$10 per MTok.")
    else:
        st.info("No LLM calls yet this session.")

    st.subheader("Semantic contract (governed KPI definitions)")
    contract = db.load_contract()
    _visible = db.allowed_kpis(role_id)          # domain-level RBAC, not all 7
    kpi_pick = st.selectbox("KPI", list(_visible),
                            format_func=lambda k: contract["kpis"][k]["name"])
    st.code(yaml.dump({kpi_pick: contract["kpis"][kpi_pick]}, sort_keys=False,
                      allow_unicode=True), language="yaml")

    st.subheader("Security model in force")
    role = roles[role_id]
    st.markdown(f"""
    - **Row-level**: `{role_id}` sees regions **{role['regions'] if role['regions'] != 'all' else 'all'}** : enforced via SQL `WHERE` injection in the query layer, on every KPI, driver and contribution query.
    - **Column-level**: enterprise account names are **{'masked (stable ACCT-codes)' if role['mask_accounts'] else 'visible'}** for this role : applied to evidence snippets and LLM prompts, not just the UI.
    - **Domain-level**: this role can access **{len(db.allowed_kpis(role_id))} of {len(contract['kpis'])}** governed KPIs (per-KPI `access` lists in the contract).
    """)
