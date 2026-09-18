"""Streaming replay: the same detection rule the batch engine uses, at daily grain."""
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
from ui.common import (C, FONT_MONO, base_layout, fmt, pd, section_label)


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

    st.header("Live feed")
    st.caption(
        "The event stream, replayed in accelerated time — orders, shipments, SLA "
        "breaches, complaints and churn landing day by day. Each monitor runs the "
        "same statistical rule as the batch signal gate against a pre-incident "
        "baseline, so you can watch an anomaly get caught as it happens.")

    if "sc" not in st.session_state:
        st.session_state.sc = stream.REPLAY_START
        st.session_state.playing = False
        st.session_state.alerted = []

    # transport rail : flat controls + a recording lamp, no card
    c1, c2, c3, c4 = st.columns([1, 1, 1.5, 1.8])
    if c1.button("▶ Run" if not st.session_state.playing else "⏸ Pause",
                 type="primary", width="stretch", key="play_btn"):
        st.session_state.playing = not st.session_state.playing
        st.rerun()
    if c2.button("↺ Restart", width="stretch", key="reset_stream"):
        st.session_state.sc = stream.REPLAY_START
        st.session_state.playing = False
        st.session_state.alerted = []
        st.rerun()
    speed = c3.select_slider("Speed", options=[1, 2, 3, 5], value=2,
                             format_func=lambda v: f"{v} day/tick", key="stream_speed")
    _lamp = C["critical"] if st.session_state.playing else C["muted"]
    _word = "recording" if st.session_state.playing else "paused"
    c4.markdown(
        f"<div style='padding-top:30px'>"
        f"<span style='color:{_lamp}'>●</span> "
        f"<span style='color:{C['ink2']};font-size:0.85rem;font-weight:600'>{_word}</span>"
        f"<span style='font-family:{FONT_MONO};color:{C['muted']};font-size:0.72rem'>"
        f"&nbsp;&nbsp;{stream.REPLAY_START:%d %b} – {stream.REPLAY_END:%d %b %Y}</span>"
        f"</div>", unsafe_allow_html=True)

    _TOTAL_DAYS = (stream.REPLAY_END - stream.REPLAY_START).days + 1

    def _figure(v, label):
        return (f"<div><div style='font-family:{FONT_MONO};font-size:1.3rem;"
                f"font-weight:500;font-variant-numeric:tabular-nums;color:{C['ink']};"
                f"line-height:1.2'>{v}</div>"
                f"<div style='font-size:0.75rem;color:{C['muted']}'>{label}</div></div>")

    def _zmeter(z, breached):
        zc = max(-3.0, min(3.0, z))
        pos = (zc + 3) / 6 * 100
        dot = C["critical"] if breached else C["ink2"]
        rails = "".join(
            f"<div style='position:absolute;top:0;bottom:0;left:{r}%;width:1px;"
            f"background:{C['axis']}'></div>" for r in (100 / 6, 500 / 6))
        return (
            f"<div style='position:relative;height:12px;margin:10px 0 1px'>"
            f"<div style='position:absolute;top:5px;left:0;right:0;height:2px;"
            f"background:{C['band']}'></div>{rails}"
            f"<div style='position:absolute;top:2px;left:calc({pos}% - 4px);width:8px;"
            f"height:8px;border-radius:50%;background:{dot}'></div></div>"
            f"<div style='display:flex;justify-content:space-between;"
            f"font-family:{FONT_MONO};font-size:0.66rem;color:{C['muted']}'>"
            f"<span>−{stream.BREACH_Z:g}</span><span>z {z:+.2f}</span>"
            f"<span>+{stream.BREACH_Z:g}</span></div>")

    def _monitor(s):
        breached = s["breached"]
        val = (fmt(s["current"], "INR") if s["unit"] == "INR"
               else f"{s['current']:.1f}%" if s["unit"] == "%"
               else f"{s['current']:.1f}")
        state = (f"<span style='white-space:nowrap'>"
                 f"<span style='color:{C['critical'] if breached else C['good']};"
                 f"font-size:0.7rem'>▪</span> <span style='color:{C['ink2']};"
                 f"font-size:0.74rem;font-weight:600'>"
                 f"{'breached' if breached else 'steady'}</span></span>")
        dcol = C["critical_text"] if breached else C["muted"]
        arrow = "▲" if s["pct"] > 0 else "▼"
        top = f"border-top:2px solid {C['critical']};" if breached else ""
        return (
            f"<div style='border:1px solid {C['border']};{top}border-radius:3px;"
            f"background:{C['panel']};padding:11px 14px'>"
            f"<div style='display:flex;justify-content:space-between;align-items:baseline'>"
            f"<span style='font-size:0.8rem;font-weight:500;color:{C['muted']}'>"
            f"{s['label']} — {s['region']}</span>{state}</div>"
            f"<div style='font-family:{FONT_MONO};font-size:1.7rem;font-weight:500;"
            f"font-variant-numeric:tabular-nums;color:{C['ink']};line-height:1.25'>{val}</div>"
            f"<div style='font-size:0.78rem;color:{dcol}'>{arrow} {abs(s['pct']):.1f}% "
            f"vs baseline</div>{_zmeter(s['z'], breached)}</div>")

    @st.fragment(run_every=1.1 if st.session_state.playing else None)
    def live_panel():
        if st.session_state.playing:
            nxt = st.session_state.sc + pd.Timedelta(days=speed).to_pytimedelta()
            st.session_state.sc = stream.clamp(nxt)
            if st.session_state.sc >= stream.REPLAY_END:
                # End of tape. `run_every` was bound when the fragment was
                # decorated by the OUTER script, so clearing the flag in here
                # does not stop the timer: the fragment kept polling (and doing
                # real DuckDB work) every 1.1s for the rest of the session, while
                # the transport rail outside still showed 'Pause'. Rerun at app
                # scope so the fragment is re-decorated with run_every=None.
                st.session_state.playing = False
                st.rerun()
        cur = st.session_state.sc
        tot = stream.totals_to(cur, role_id)
        status = stream.live_status(cur, role_id)
        breached = [s for s in status if s["breached"]]

        # figures row left, the clock as the single hero on the right
        fig_html = "".join((
            _figure(f"{tot['events']:,}", "Events ingested"),
            _figure(f"{tot['orders']:,}", "orders"),
            _figure(f"{tot['shipments']:,}", "shipments"),
            _figure(f"{tot['complaints']:,}", "complaints"),
            _figure(fmt(tot["revenue"], "INR"), "revenue in window"),
        ))
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;align-items:flex-end;"
            f"border-top:1px solid {C['border']};border-bottom:1px solid {C['border']};"
            f"padding:12px 2px;margin:6px 0 2px'>"
            f"<div style='display:flex;gap:34px'>{fig_html}</div>"
            f"<div style='text-align:right'>"
            f"<div style='font-family:{FONT_MONO};font-size:1.75rem;font-weight:500;"
            f"color:{C['ink']};line-height:1.1'>{cur:%d %b %Y}</div>"
            f"<div style='font-size:0.75rem;color:{C['muted']}'>"
            f"day {tot['days']} of {_TOTAL_DAYS}</div></div></div>",
            unsafe_allow_html=True)

        for s in breached:
            if s["key"] not in st.session_state.alerted:
                st.session_state.alerted.append(s["key"])
                st.toast(f"{s['label']} breached in {s['region']}", icon="🚨")

        # alarm strip : the only element with a colored ground
        if breached:
            names = ", ".join(f"{s['label']} ({s['region']})" for s in breached)
            st.markdown(
                f"<div style='padding:10px 14px;margin-top:10px;"
                f"border-left:3px solid {C['critical']};background:{C['critical']}14;"
                f"color:{C['ink']};font-weight:600'>Threshold breached : {names}. "
                f"The batch engine would open an investigation at the next scan.</div>",
                unsafe_allow_html=True)
            if st.button("Investigate this now", type="primary", key="live_to_inv"):
                ctx.nav.investigate(
                    "fulfilment_sla" if any(s["key"] == "fulfilment_sla" for s in breached)
                    else "revenue", period="2026-07")

        section_label("Live monitors")
        st.caption("Rolling 7-day value for the worst region, against its own pre-incident "
                   "baseline. The meter shows where today's z sits between the breach rails.")
        mcols = st.columns(len(status) or 1)
        for mc, s in zip(mcols, status):
            mc.markdown(_monitor(s), unsafe_allow_html=True)

        section_label("Arrivals per day")
        ser = stream.series_to(cur, role_id)
        fig = go.Figure()
        fig.add_trace(go.Bar(x=ser["day"], y=ser["orders"], name="orders",
                             marker_color=C["series"], opacity=0.45,
                             hovertemplate="%{x}: %{y:,} orders<extra></extra>"))
        fig.add_trace(go.Scatter(x=ser["day"], y=ser["complaints"], name="complaints",
                                 mode="lines", line=dict(color=C["warning"], width=2),
                                 yaxis="y2",
                                 hovertemplate="%{x}: %{y} complaints<extra></extra>"))
        base_layout(fig, 240)
        fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False,
                                      tickfont=dict(size=9, color=C["muted"])),
                          showlegend=True,
                          legend=dict(orientation="h", y=1.14, font=dict(size=10)))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False},
                        key="live_vol")

        # the tape : a chart-recorder log with a date gutter; alarms print in flame
        section_label("Tape")
        kind_color = {"high": C["critical_text"], "warn": C["warning_text"],
                      "info": C["muted"]}
        rows = stream.recent_events(cur, role_id)

        def _tape_row(e):
            day = pd.Timestamp(e["day"]).strftime("%d %b")
            alarm = e["sev"] == "high"
            edge = (f"border-left:3px solid {C['critical']};background:{C['critical']}10;"
                    if alarm else "border-left:3px solid transparent;")
            return (f"<div style='{edge}display:flex;gap:14px;padding:4px 10px;"
                    f"border-bottom:1px solid {C['grid']}'>"
                    f"<span style='font-family:{FONT_MONO};font-size:0.72rem;"
                    f"color:{C['muted']};min-width:44px;padding-top:2px'>{day}</span>"
                    f"<span style='font-size:0.7rem;font-weight:600;"
                    f"color:{kind_color[e['sev']]};min-width:76px;padding-top:2px'>"
                    f"{e['kind'].lower()}</span>"
                    f"<span style='font-family:{FONT_MONO};font-size:0.79rem;"
                    f"color:{C['ink']}'>{e['text']}</span></div>")

        tape = "".join(_tape_row(e) for e in rows) or (
            f"<div style='padding:10px;color:{C['muted']}'>waiting for events…</div>")
        st.markdown(f"<div style='border:1px solid {C['border']};border-radius:3px;"
                    f"max-height:300px;overflow:auto'>{tape}</div>",
                    unsafe_allow_html=True)

    live_panel()
