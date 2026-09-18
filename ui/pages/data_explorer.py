"""Raw source inspection, row- and column-filtered for the signed-in role."""
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
from ui.common import (C, base_layout, pd, section_label, stat_tile)


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

    st.header("Data : the live feed behind every number")
    st.caption("Redash-style explorer over the governed sources. Every query below runs "
               "against the same tables the engine reads, with this role's row-level "
               "security applied : nothing is precomputed.")

    _DATE_COLS = db.DATE_COLS      # single source: engine/db.py
    fresh = db.source_freshness()
    c1, c2, c3 = st.columns([2, 1, 2])
    src = c1.selectbox("Source", list(_DATE_COLS),
                       format_func=lambda s: f"{fresh[s]['system']}  ·  {s}")
    grain = c2.radio("Grain", ["day", "week", "month"], index=2, horizontal=True)
    dmax = pd.Timestamp(fresh[src]["as_of"]).date()
    dmin = min(pd.Timestamp("2025-08-01").date(), dmax)   # never let min exceed max
    drange = c3.slider("Time range", min_value=dmin, max_value=dmax, value=(dmin, dmax),
                       format="YYYY-MM-DD")

    # SQL construction lives in engine/explore.py: sources and grains are
    # allowlisted and the date bounds are bound parameters, so the slider
    # cannot reach the statement.
    t0 = time.perf_counter()
    try:
        vol_sql, vol = explore.volume(src, grain, role_id, drange[0], drange[1])
        _, latest = explore.latest_rows(src, role_id, drange[0], drange[1])
    except Exception as e:
        st.error(f"Query failed: {e}")
        st.stop()
    q_ms = (time.perf_counter() - t0) * 1000
    total_rows = int(vol["rows_"].sum()) if not vol.empty else 0

    s1, s2, s3, s4 = st.columns(4)
    s1.markdown(stat_tile("Rows in range", f"{total_rows:,}",
                          sub=f"{src} · {fresh[src]['grain']}", accent=C["series"]),
                unsafe_allow_html=True)
    s2.markdown(stat_tile("Freshness", fresh[src]["as_of"],
                          sub=f"refreshed {fresh[src]['refresh']}", accent=C["good"]),
                unsafe_allow_html=True)
    s3.markdown(stat_tile("Query time", f"{q_ms:,.0f} ms",
                          sub="DuckDB, computed on click", accent=C["series"]),
                unsafe_allow_html=True)
    s4.markdown(stat_tile("Your data scope",
                          "all regions" if roles[role_id]["regions"] == "all"
                          else ", ".join(roles[role_id]["regions"]),
                          sub="row-level security applied in SQL", accent=C["warning"]),
                unsafe_allow_html=True)

    section_label(f"Volume over time · rows per {grain}")
    if not vol.empty:
        vfig = go.Figure(go.Bar(x=vol["bucket"], y=vol["rows_"], marker_color=C["series"],
                                hovertemplate="%{x}: %{y:,} rows<extra></extra>"))
        base_layout(vfig, 240)
        vfig.update_layout(bargap=0.25)
        st.plotly_chart(vfig, width="stretch", config={"displayModeBar": False},
                        key=f"vol_{src}_{grain}")
    else:
        st.info("No rows in the selected range for your data scope.")

    section_label("SQL executed · row-level security clause included")
    st.code(" ".join(vol_sql.split()), language="sql")

    section_label("Latest 50 records in range · sensitive columns masked per role")
    for mask_col in ("account", "account_name"):
        if mask_col in latest.columns:
            latest[mask_col] = latest[mask_col].astype(str).map(
                lambda v: db.mask_text(v, role_id))
    st.dataframe(latest, hide_index=True, width="stretch", height=320)
