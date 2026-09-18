"""The reasoning pyramid for one KPI: verdict, evidence, actions, audit trail."""
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
from services import intent as intent_service
from services import scan as scan_service
from ui.common import (C, badge, confidence_components, confidence_gauge,
                       contribution_waterfall, delta_bar, fmt,
                       gate_bullets, hypothesis_bars, method_strip,
                       monthly_impact, pd, render_actions, section_label,
                       sparkline, stat_tile)


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

    st.header("Investigation")
    kpis = db.allowed_kpis(role_id)
    ids = list(kpis)

    # --- ask in plain English (LLM-assisted intent understanding) ---
    with st.form("ask_form", border=False):
        q = st.text_input("Ask a question in plain English", key="ask_box",
                          placeholder='e.g. "Why did revenue fall in July?" or "What happened to complaints?"')
        asked = st.form_submit_button("Ask")
    # Gated on submit. `if q:` re-ran on every rerun while text stayed in the
    # box: it re-set kpi_sel before the selectbox existed (so the dropdown
    # snapped back and could not be changed by hand), auto-ran a new
    # investigation whenever the period changed, and in live mode fired a
    # blocking Haiku intent call on every single widget interaction.
    if q and asked:
        # keyword scoring, then a live-only model fallback (services/intent.py)
        matched, how = intent_service.resolve(q, kpis, llm)
        if matched:
            st.session_state.kpi_sel = matched
            st.session_state._autorun = True
            st.caption(f"Understood as: **{kpis[matched]['name']}** ({how})")
        else:
            st.warning("I couldn't map that to a governed KPI. Try naming one: " +
                       ", ".join(kpis[k]["name"] for k in ids))

    if "kpi_sel" not in st.session_state or st.session_state.kpi_sel not in ids:
        st.session_state.kpi_sel = "revenue" if "revenue" in ids else ids[0]
    kpi_id = st.selectbox("KPI", ids, key="kpi_sel", format_func=lambda k: kpis[k]["name"])
    cfg = kpis[kpi_id]

    key = (kpi_id, role_id, PERIOD)
    c1, c2 = st.columns([1, 5])
    # pop FIRST: `or` short-circuits, so clicking the button left the flag
    # set and the investigation re-fired on the next rerun.
    autorun = st.session_state.pop("_autorun", False)
    run = c1.button("▶ Run investigation", type="primary", key="run_btn") or autorun
    if c2.button("Re-run (ignore cache)", key="rerun_btn"):
        st.session_state.investigations.pop(key, None)
        run = True
    if run and key not in st.session_state.investigations:
        try:
            with st.spinner("🧭 Investigation in progress…", show_time=True):
                result = pyramid.investigate(kpi_id, PERIOD, role_id, llm)
        except Exception as e:
            st.error(f"The investigation could not complete: {e}")
            st.caption("Nothing was concluded, so nothing is shown : the engine fails "
                       "closed rather than presenting a partial answer.")
            st.stop()
        st.session_state.investigations[key] = result
        st.toast(f"Investigation complete in {result.get('wall_ms', 0)/1000:.1f}s", icon="✅")

    r = st.session_state.investigations.get(key)
    if r is None:
        st.info("Ask a question above, or pick a KPI and run the investigation. Flagged KPIs "
                "on the dashboard deep-link here.")
    else:
        an, conf = r["anomaly"], r["confidence"]
        outcome_style = {
            "actions": ("✅ ROOT CAUSE ESTABLISHED : ACTIONS RECOMMENDED", C["good"]),
            "tentative": ("🟡 TENTATIVE : likely cause found; confirm before committing", C["warning"]),
            "abstain": ("⛔ ABSTAINED : evidence insufficient/contradictory; escalated to a human expert", C["critical"]),
            "sparse": ("◔ TOO NEW TO DIAGNOSE : monitoring with widened bands", C["warning"]),
            "no_signal": ("✓ NO SIGNAL : movement within normal variation", C["good"]),
        }.get(r["outcome"], (f"• {r['outcome'].upper()}", C["ink2"]))

        # ---- verdict row: the metric's own chart + the decision, side by side ----
        section_label("The verdict")
        vL, vR = st.columns([3, 2])
        with vL:
            st.plotly_chart(sparkline(r["series"], an, cfg, PERIOD, height=252), width="stretch",
                            config={"displayModeBar": False}, key=f"inv_trend_{kpi_id}")
            cap = []
            if not an["sparse"]:
                cap.append("shaded band = this KPI's normal range")
            cap.append(("red" if an.get("material") else "highlighted")
                       + " dot = the analysis month")
            if not an["sparse"] and len(r["series"]) >= 7:
                cap.append("dotted trend = 3-month OLS forecast (90% interval)")
            st.caption(" · ".join(cap))
        with vR:
            st.markdown(f"<div style='padding:8px 12px;border:1px solid {outcome_style[1]}55;"
                        f"border-left:4px solid {outcome_style[1]};border-radius:8px;"
                        f"background:{outcome_style[1]}14;font-weight:600;color:{C['ink']}'>"
                        f"{outcome_style[0]}</div>", unsafe_allow_html=True)
            st.plotly_chart(confidence_gauge(conf), width="stretch",
                            config={"displayModeBar": False}, key=f"gauge_{kpi_id}")
            if conf.get("sparse_capped"):
                st.caption("sparse-history cap applied to confidence")
            imp = monthly_impact(an, r["unit"])
            facts = [f"**{fmt(an['current'], r['unit'])}** this month"]
            if an["pct_vs_recent"] is not None:
                facts.append(f"**{an['pct_vs_recent']:+.1f}%** vs recent months")
            if imp is not None:
                facts.append(f"≈ **{fmt(imp, 'INR')}/month** vs baseline")
            if not is_exec and an.get("q_value") is not None:
                facts.append(f"p = **{an['p_value']:.3f}**, q = **{an['q_value']:.3f}** "
                             f"(FDR-controlled across {an.get('family_size', 0)} KPIs)")
            elif not is_exec and an["z"] is not None:
                facts.append(f"z = **{an['z']}**")
            st.markdown("  \n".join(facts))
        method_strip(r)

        # ---- why it moved: charts lead, prose supports ----
        n = r["narrative"]
        has_hyp = bool(r["hypotheses"])
        section_label("Why it moved · Ranked explanatory drivers" if has_hyp
                      else "What the engine concluded")
        st.markdown(f"#### {n['headline']}")
        if has_hyp:
            wL, wR = st.columns([5, 4])
            with wL:
                st.plotly_chart(hypothesis_bars(r["hypotheses"]), width="stretch",
                                config={"displayModeBar": False}, key=f"hyp_{kpi_id}")
                st.caption("bar length = computed strength (movement + evidence + external "
                           "confirmation) · gray = no evidence backs it")
            with wR, st.container(border=True):
                st.caption("In plain words : written from the computed facts above")
                st.markdown(f"<div style='font-size:1.02rem;line-height:1.65;color:{C['ink']}'>"
                            f"{n['body']}</div>", unsafe_allow_html=True)
                if r.get("snippets"):
                    cited = [s for s in r["snippets"]
                             if f"[{s['id']}]" in n.get("body", "")] or r["snippets"][:3]
                    st.caption("evidence behind this:")
                    pcols = st.columns(min(len(cited), 3))
                    for pc, s in zip(pcols, cited):
                        with pc.popover(f"{s['id']} · {s['file'].split(':')[0][:22]}"):
                            st.caption(f"source: {db.system_for_snippet(s)} · {s['date']}")
                            st.write(s["text"][:500])
        else:
            st.write(n["body"])
        for h in r.get("hypotheses", []):
            if h.get("unexplained"):
                st.markdown(badge(
                    f"⚠ {h['label'].split(' moved')[0]} moved with this KPI, but nothing "
                    "upstream explains why it moved : treated as a lead, not as "
                    "corroboration", C["warning_text"]), unsafe_allow_html=True)
        for d in r.get("contradictions", []):
            st.markdown(badge(f"✗ contradicting driver: {d['label']} moved the wrong way "
                              f"(z={d['z']:.1f})", C["critical_text"]), unsafe_allow_html=True)
        if r.get("unvalidated_lead"):
            st.markdown(badge("⚠ unvalidated lead (LLM-proposed, blocked by the hallucination "
                              f"guard): {r['unvalidated_lead']}", C["warning_text"]),
                        unsafe_allow_html=True)

        # ---- where the movement sits (region view) ----
        contrib_tables = (r.get("contribution") or {}).get("tables", {})
        reg_table = contrib_tables.get("region")
        if reg_table is not None and not reg_table.empty:
            section_label("Where the movement sits · by region, vs 3-month baseline")
            dim_unit = cfg.get("dim_unit", r["unit"])
            bad_when = "up" if cfg.get("good_direction", "up") == "down" else "down"
            if (r.get("contribution") or {}).get("concentration") == "diffuse":
                st.caption("No region stands out : the movement is spread evenly across "
                           "all of them, which argues against a regional cause and "
                           "towards something systemic (a process or measurement change).")
            if cfg.get("dim_additive", True):
                st.plotly_chart(contribution_waterfall(reg_table, r["unit"]), width="stretch",
                                config={"displayModeBar": False}, key=f"wf_{kpi_id}")
            else:
                st.plotly_chart(delta_bar(reg_table, dim_unit, bad_when=bad_when),
                                width="stretch",
                                config={"displayModeBar": False}, key=f"wf_{kpi_id}")
        if has_hyp:
            with st.expander("Hypothesis details : evidence IDs, sources, full labels"):
                hdf = pd.DataFrame([{
                    "rank": h.get("rank"), "hypothesis": h["label"],
                    "strength": h.get("strength", 0.0),
                    "evidence": ", ".join(h["snippets"]) or "—",
                    "external": "yes" if h["events"] else "—",
                    "status": "corroborated" if (h["snippets"] or h["events"]) else "UNCORROBORATED",
                } for h in r["hypotheses"]]).sort_values("rank")
                st.dataframe(hdf, hide_index=True, width="stretch", column_config={
                    "strength": st.column_config.ProgressColumn(
                        "strength", min_value=0.0, max_value=1.0, format="%.2f")})

        # ---- what to do about it ----
        if n.get("actions") or n.get("clarifying_question") or n.get("escalation_brief"):
            section_label("Low-regret steps while confirming" if r["outcome"] == "tentative"
                          else "What to do about it")
        if n.get("actions"):
            render_actions(n["actions"], cfg)
        if n.get("clarifying_question"):
            st.warning(f"**The engine needs a human answer first:** {n['clarifying_question']}")
        if n.get("escalation_brief"):
            with st.container(border=True):
                st.markdown("**Level 4 : expert escalation brief** (ready to send)")
                st.write(n["escalation_brief"])
        if n.get("what_could_change"):
            st.info(f"**What could change this answer:** {n['what_could_change']}")
        if n.get("caveats"):
            st.caption(f"Caveats: {n['caveats']}")

        # ---- audit trail ----
        st.subheader("How we got here : audit trail")
        LEVEL_LABEL = {"1": "SQL, statistics & machine learning",
                       "2": "document retrieval + language model",
                       "3": "rule-based matching", "G": "statistics",
                       "4": "language model"}
        for lv in r["levels"]:
            gate = lv.get("gate")
            head = (f"**Level {lv['level']} : {lv['name']}** · "
                    f"{LEVEL_LABEL.get(str(lv['level']), '')}")
            with st.expander(head, expanded=(not is_exec and str(lv["level"]) in ("1", "G"))):
                st.write(lv["summary"])
                if gate:
                    st.markdown(f"**{gate['name']} : {'passed' if gate['passed'] else 'failed'}.** "
                                f"{gate['detail']}")
                if str(lv["level"]) == "1" and gate and not an["sparse"] \
                        and an.get("z") is not None and not is_exec:
                    st.plotly_chart(gate_bullets(an, cfg), width="stretch",
                                    config={"displayModeBar": False},
                                    key=f"gatebul_{kpi_id}")
                if str(lv["level"]) == "G":
                    st.markdown("**Why the confidence is what it is** (weighted ingredients):")
                    st.plotly_chart(confidence_components(r["confidence"]), width="stretch",
                                    config={"displayModeBar": False}, key=f"comps_{kpi_id}")
                if lv.get("confidence_after") is not None:
                    st.caption(f"confidence after this level: {lv['confidence_after']:.2f}")
                if lv["level"] == 1 and lv.get("votes"):
                    st.markdown("**Three independent checks ran before anything else:**")
                    vcols = st.columns(len(lv["votes"]))
                    for vc, v in zip(vcols, lv["votes"]):
                        vc.markdown(stat_tile(
                            v["detector"], "Flagged" if v["flag"] else "Clear",
                            delta_txt=None,
                            sub=v["detail"],
                            accent=C["critical"] if v["flag"] else C["good"]),
                            unsafe_allow_html=True)
                if lv["level"] == 1 and lv.get("sql") and not is_exec:
                    st.markdown("**SQL executed** (row-level security clause injected for this role):")
                    st.code(lv["sql"], language="sql")
                if lv["level"] == 1 and "contribution" in lv:
                    st.markdown("**Where the movement sits** (Δ vs 3-month baseline):")
                    tabs = st.tabs([d.title() for d in lv["contribution"]])
                    for tab, (dim, table) in zip(tabs, lv["contribution"].items()):
                        with tab:
                            cA, cB = st.columns([3, 2])
                            cA.plotly_chart(
                                delta_bar(table, cfg.get("dim_unit", r["unit"]),
                                          bad_when="up" if cfg.get("good_direction", "up") == "down"
                                          else "down"),
                                width="stretch", config={"displayModeBar": False},
                                key=f"contrib_{kpi_id}_{dim}")
                            cB.dataframe(table.round(1), hide_index=True, height=230)
                    if lv.get("drivers"):
                        st.markdown("**Driver check** : causal links from the semantic contract, "
                                    "each tested for concurrent movement (z) plus a descriptive "
                                    "co-movement statistic (Pearson r of MoM changes, 12m incl. "
                                    "this month : not independent proof; the evidence gate does "
                                    "the corroborating):")
                        ddf = pd.DataFrame(lv["drivers"])[["label", "relation", "z", "pct",
                                                           "corr", "status", "note"]] \
                            .rename(columns={"corr": "co-move r (12m)"})
                        st.dataframe(ddf, hide_index=True)
                    else:
                        st.caption("No causal drivers declared in the contract for this KPI : "
                                   "corroboration relies on retrieved evidence and external events.")
                if lv["level"] == 2 and lv.get("snippets"):
                    st.caption("retrieval query terms: " +
                               ", ".join(f"{t}×{w:g}" for t, w in lv["query_terms"]))
                    for s in lv["snippets"]:
                        supports = [m for m in lv["mappings"] if m["snippet_id"] == s["id"]]
                        sup = supports[0].get("supports", []) if supports else []
                        tagline = f"→ supports {', '.join(sup)}" if sup else "→ not evidence"
                        with st.container(border=True):
                            st.markdown(f"**[{s['id']}]** `{s['file']}` · {s['date']} · "
                                        f"{db.system_for_snippet(s)} · score {s['score']} · **{tagline}**")
                            st.caption(s["text"][:400] + ("…" if len(s["text"]) > 400 else ""))
                if lv["level"] == 3 and lv.get("events"):
                    for ev in lv["events"]:
                        st.markdown(f"**{ev['date']}** : {ev['headline']}")
                        st.caption(f"matched on: {', '.join(ev['tags'])} · source: {ev['source']}")

        # ---- run telemetry ----
        with st.expander("Under the hood for this run : latency, tokens & cost"):
            recs = r.get("telemetry", [])
            wall = r.get("wall_ms", 0)
            if recs:
                st.dataframe(pd.DataFrame(recs)[["task", "model", "mode", "latency_ms",
                                                 "input_tokens", "output_tokens", "cost_usd", "cost_inr"]],
                             hide_index=True)
                s = telemetry.summarize(recs)
                st.caption(f"end-to-end {wall/1000:.1f}s wall · {s['llm_calls']} LLM call(s) · "
                           f"{s['input_tokens']}+{s['output_tokens']} tokens · ${s['cost_usd']} "
                           f"(₹{s['cost_inr']}) · non-LLM analytics ran in "
                           f"{max(wall - s['total_latency_ms'], 0)/1000:.2f}s")
            else:
                st.caption(f"end-to-end {wall/1000:.2f}s : fully deterministic path, zero LLM tokens "
                           "(signal gate / sparse guard).")

        # ---- feedback ----
        if r.get("inv_id"):
            st.subheader("Was this diagnosis right?")
            fc1, fc2, fc3 = st.columns([1, 1, 4])
            comment = fc3.text_input("Correction / note (stored in the decision ledger)",
                                     key=f"fb_txt_{r['inv_id']}")
            # Record the verdict against the RANK-1 driver, which is the claim
            # the human is actually judging. That is what lets a correction
            # change a later answer instead of just sitting in the log.
            _top = next((h for h in r.get("hypotheses", []) if h.get("rank") == 1), None)
            _judged = (_top or {}).get("driver_id", "")
            _voted = st.session_state.setdefault("_voted", set())
            if r["inv_id"] in _voted:
                st.caption("Verdict recorded for this investigation.")
            else:
                if fc1.button("👍 Correct", key=f"up_{r['inv_id']}"):
                    fb.log_feedback(r["inv_id"], "up", comment, kpi=kpi_id,
                                    period=PERIOD, driver=_judged)
                    _voted.add(r["inv_id"])
                    st.toast("Logged : this explanation will rank higher next time.", icon="✅")
                if fc2.button("👎 Wrong", key=f"dn_{r['inv_id']}"):
                    fb.log_feedback(r["inv_id"], "down", comment, kpi=kpi_id,
                                    period=PERIOD, driver=_judged)
                    _voted.add(r["inv_id"])
                    st.toast("Logged : this explanation will be demoted next time.",
                             icon="📝")
