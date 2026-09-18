"""Every investigation, its confidence, and any human verdict on it."""
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
from ui.common import (pd)


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

    st.header("Decision Ledger")
    st.caption("Every investigation, conclusion, confidence score and user correction is appended "
               "here. Past-period entries are part of the Level-2 retrieval corpus, so the engine "
               "recalls precedent : the RECALL step and the learning loop.")
    try:
        entries = fb.read_ledger()
    except Exception as e:
        entries = []
        st.error(f"Could not read the decision ledger: {e}")
    # Column- and domain-security are applied HERE, at read time for the viewing
    # role — entries were masked for whoever ran the investigation, which is a
    # different role than whoever is reading the page now.
    visible_kpis = set(db.allowed_kpis(role_id)) | {"feedback"}
    entries = [e for e in entries if e.get("kpi") in visible_kpis]
    for e in entries:
        e["summary"] = db.mask_text(str(e.get("summary", "")), role_id)
    if entries:
        df = pd.DataFrame(entries)[::-1]
        st.dataframe(df[["id", "timestamp", "kpi", "period", "outcome", "confidence", "summary"]],
                     hide_index=True, width="stretch", height=420)
        st.caption(f"Showing {len(entries)} entries visible to **{role_id}** : "
                   "masked and domain-filtered for this role.")
    else:
        st.info("Ledger empty : run an investigation.")
