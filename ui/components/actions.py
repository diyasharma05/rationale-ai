"""Recommended-action cards: lever, owner, decision right, monitoring."""

import re

import streamlit as st

from engine import policy
from ui.theme import C


def render_actions(actions, cfg):
    def row(label, value):
        return (f"<div style='margin:3px 0'><span style='color:{C['muted']};"
                f"font-size:0.8rem'>{label}</span><br>"
                f"<span style='color:{C['ink']};font-size:0.92rem'>{value}</span></div>")

    for row_start in range(0, len(actions), 2):
        cols = st.columns(2)
        for col, a in zip(cols, actions[row_start:row_start + 2]):
            with col, st.container(border=True):
                st.markdown(f"**{a.get('action', '')}**")
                st.caption("for: " + re.sub(r"^\s*H\d+\s*[:.\-]\s*", "", a.get("driver", "—"))
                           + f" · confidence {a.get('confidence', '—')}")
                st.markdown(
                    row("Owner · Decision right",
                        f"{a.get('owner', '—')} : {policy.lever_approval(cfg, a.get('lever', ''))}")
                    + row("Expected impact", a.get("expected_impact", "—"))
                    + row("How we'll know it's working", a.get("monitoring", "—")),
                    unsafe_allow_html=True)
