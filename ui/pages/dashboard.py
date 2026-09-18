"""Triage view: what moved, how much it costs, and what to look at first."""
import json as _json
import os
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml

import feedback as fb
import metrics
import telemetry
from engine import (anomaly, confidence, db, economics, explore, policy,
                    pyramid, screening, stats_ml, stream)
from llm import prompts
from services import intent as intent_service
from services import scan as scan_service
from ui.common import (C, fmt, human_line, month_name, monthly_impact,
                       pill, section_label, severity_order, sparkline,
                       stat_tile)


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

    _t0 = time.perf_counter()
    try:
        scan = scan_service.scan(role_id, PERIOD)
    except Exception as e:
        st.error(f"Could not compute the KPI scan: {e}")
        st.caption("The deterministic layer failed — check the data sources under Data.")
        st.stop()
    _scan_ms = (time.perf_counter() - _t0) * 1000
    kpi_ids = severity_order(scan)
    metrics.record_scan(PERIOD, role_id, len(kpi_ids),
                        sum(1 for k in kpi_ids if scan[k][2]["material"]))
    flagged_ids = [k for k in kpi_ids if scan[k][2]["material"]]
    sparse_ids = [k for k in kpi_ids if scan[k][2]["sparse"]]

    total_imp = sum(i for i in (monthly_impact(scan[k][2], scan[k][0]["unit"])
                                for k in flagged_ids) if i is not None)
    worst = flagged_ids[0] if flagged_ids else None
    fresh = db.source_freshness()
    systems = {v["system"]: v for v in fresh.values()}

    st.header(f"Business Health : {month_name(PERIOD)}")
    if flagged_ids:
        lead = scan[worst][0]["name"].split(" (")[0]
        st.caption(f"**{len(flagged_ids)} of {len(kpi_ids)} KPIs** moved outside their normal "
                   f"range this month, putting about **{fmt(total_imp, 'INR')}/month** at "
                   f"stake; the sharpest mover is **{lead}**. "
                   f"Signed in as **{roles[role_id]['label']}**.")
    else:
        st.caption(f"All KPIs inside their normal range in {month_name(PERIOD)}. "
                   f"Signed in as **{roles[role_id]['label']}**.")
    st.caption(f"⏱ computed live just now : {len(kpi_ids)} KPIs scanned across "
               f"{len(systems)} systems in **{_scan_ms:,.0f} ms**")

    # --- overview stat row (Grafana-style top panels) ---
    section_label("This month at a glance")
    o1, o2, o3, o4 = st.columns(4)
    o1.markdown(stat_tile("KPIs needing attention", f"{len(flagged_ids)} / {len(kpi_ids)}",
                          chip=f"{len(sparse_ids)} building baseline" if sparse_ids else None,
                          sub="severity-ordered below",
                          accent=C["critical"] if flagged_ids else C["good"]),
                unsafe_allow_html=True)
    o2.markdown(stat_tile("Est. revenue impact", f"{fmt(total_imp, 'INR')} /mo",
                          delta_txt="▼ vs baseline" if total_imp < 0 else "▲ vs baseline",
                          delta_color=C["critical_text"] if total_imp < 0 else C["good_text"],
                          sub="flagged KPIs, vs 12-month baseline", accent=C["critical"]),
                unsafe_allow_html=True)
    o3.markdown(stat_tile("Largest deviation",
                          scan[worst][0]["name"].split(" (")[0] if worst else "—",
                          delta_txt=(f"{scan[worst][2]['pct_vs_recent']:+.1f}%" if worst else None),
                          delta_color=C["critical_text"],
                          chip=(None if is_exec or not worst else f"z = {scan[worst][2]['z']}"),
                          sub="most statistically extreme movement", accent=C["warning"]),
                unsafe_allow_html=True)
    o4.markdown(stat_tile("Data sources", f"{len(systems)} reconciled",
                          chip=f"latest as of {max(v['as_of'] for v in systems.values())}",
                          sub=" · ".join(f"{v['system'].split(' (')[0]}: {v['refresh'].split(' ')[0]}"
                                         for v in systems.values()),
                          accent=C["good"]), unsafe_allow_html=True)

    # --- needs-attention metrics: clickable tiles with a details popover ---
    if flagged_ids:
        section_label("Needs attention : biggest problem first · click a metric for its details")
        for row_start in range(0, len(flagged_ids), 4):
            wcols = st.columns(4)
            for wc, k in zip(wcols, flagged_ids[row_start:row_start + 4]):
                cfg, s, an = scan[k]
                imp = monthly_impact(an, cfg["unit"])
                arrow = "▲" if an["z"] > 0 else "▼"
                with wc:
                    st.markdown(stat_tile(
                        cfg["name"], fmt(an["current"], cfg["unit"]),
                        delta_txt=f"{arrow} {abs(an['pct_vs_recent']):.1f}%",
                        delta_color=C["critical_text"],
                        chip=None if is_exec else f"z = {an['z']}",
                        sub=(f"≈ {fmt(imp, 'INR')} /month vs baseline" if imp is not None
                             else "outside its normal range"),
                        accent=C["critical"]), unsafe_allow_html=True)
                    with st.popover("▸ details", width="stretch"):
                        st.markdown(f"**{cfg['name']}**")
                        st.write(human_line(cfg, an))
                        d1, d2, d3 = st.columns(3)
                        d1.metric("This month", fmt(an["current"], cfg["unit"]))
                        d2.metric("Usually", fmt(an["mean"], cfg["unit"]),
                                  delta=f"{an['pct_vs_recent']:+.1f}%", delta_color="off")
                        d3.metric("Monthly impact", fmt(imp, "INR") if imp is not None else "—")
                        if not is_exec:
                            zt = cfg["materiality"]["min_abs_z"]
                            st.caption(
                                f"normal range: {fmt(an['mean'] - zt * an['std'], cfg['unit'])} "
                                f"– {fmt(an['mean'] + zt * an['std'], cfg['unit'])} · "
                                f"z = {an['z']} (gate at ±{zt}) · owner: {cfg['owner']}")
                        src = db.load_contract()["sources"][cfg["source"]]
                        st.caption(f"source: {src['system']} · {src['grain']} · refreshed "
                                   f"{src['refresh']} · as of {fresh[cfg['source']]['as_of']}")
                        st.plotly_chart(sparkline(s, an, cfg, PERIOD, height=120), width="stretch",
                                        config={"displayModeBar": False}, key=f"pop_spark_{k}")
                        if st.button("🔍 Investigate why", key=f"pop_inv_{k}", type="primary",
                                     width="stretch"):
                            ctx.nav.investigate(k)

    section_label("Every KPI at a glance · shaded band = the metric's own normal range "
                  "(a red dot outside it is why we flagged it) · dotted line = 3-month "
                  "OLS trend forecast with 90% interval")
    for row_start in range(0, len(kpi_ids), 3):
        cols = st.columns(3)
        for col, kpi_id in zip(cols, kpi_ids[row_start:row_start + 3]):
            cfg, s, an = scan[kpi_id]
            with col, st.container(border=True):
                if an["sparse"]:
                    chip_html = pill("◔ building baseline", "warning")
                elif an["material"]:
                    chip_html = pill("⚠ needs attention", "critical")
                else:
                    chip_html = pill("✓ normal", "good")
                st.markdown(
                    f"<div style='display:flex;justify-content:space-between;align-items:center'>"
                    f"<span style='font-weight:650;color:{C['ink']}'>{cfg['name']}</span>"
                    f"{chip_html}</div>", unsafe_allow_html=True)
                delta_html = ""
                if an["pct_vs_recent"] is not None:
                    arrow = "▲" if an["pct_vs_recent"] > 0 else "▼"
                    dcol = C["critical_text"] if an["material"] else C["ink2"]
                    delta_html = (f"<span style='font-size:0.95rem;font-weight:700;color:{dcol};"
                                  f"margin-left:8px'>{arrow} {abs(an['pct_vs_recent']):.1f}%</span>")
                st.markdown(f"<div style='font-size:1.55rem;font-weight:700;"
                            f"letter-spacing:-0.025em;font-variant-numeric:tabular-nums;"
                            f"color:{C['ink']};line-height:1.2'>"
                            f"{fmt(an['current'], cfg['unit'])}{delta_html}</div>",
                            unsafe_allow_html=True)
                imp = monthly_impact(an, cfg["unit"])
                st.caption(f"≈ {fmt(imp, 'INR')} /month vs baseline" if an["material"] and imp is not None
                           else f"{cfg['name'].split(' (')[0]} · monthly · {db.load_contract()['sources'][cfg['source']]['system'].split(' (')[0]}")
                st.plotly_chart(sparkline(s, an, cfg, PERIOD), width="stretch",
                                config={"displayModeBar": False}, key=f"spark_{kpi_id}")
                b1, b2 = st.columns([1, 1])
                with b1.popover("▸ details", width="stretch"):
                    st.markdown(f"**{cfg['name']}**")
                    st.write(human_line(cfg, an))
                    st.caption(f"*{cfg['definition'].strip()}*")
                    src = db.load_contract()["sources"][cfg["source"]]
                    st.caption(f"owner: {cfg['owner']} · source: {src['system']} · "
                               f"refreshed {src['refresh']} · as of {fresh[cfg['source']]['as_of']}")
                label = ("🔍 Why?" if an["material"]
                         else ("👁 Monitor" if an["sparse"] else "Check signal"))
                if b2.button(label, key=f"inv_{kpi_id}", width="stretch"):
                    ctx.nav.investigate(kpi_id)
