"""Recommended-action cards, in the chain the brief spells out:

    driver -> controllable lever -> action -> expected impact -> owner -> confidence -> monitoring plan

The model wrote the sentences; the lever, its owner and its decision right come
from the semantic contract, resolved here through engine.policy so a card can
never show an owner the contract does not name.
"""

import re

import streamlit as st

from engine import policy
from ui.theme import C

CHAIN = ("driver", "controllable lever", "action", "expected impact", "owner", "confidence",
         "monitoring plan")


def render_actions(actions, cfg):
    def row(label, value):
        return (f"<div style='margin:3px 0'><span style='color:{C['muted']};"
                f"font-size:0.78rem;letter-spacing:0.02em'>{label}</span><br>"
                f"<span style='color:{C['ink']};font-size:0.92rem'>{value}</span></div>")

    for row_start in range(0, len(actions), 2):
        cols = st.columns(2)
        for col, a in zip(cols, actions[row_start:row_start + 2]):
            lever = a.get("lever", "") or "—"
            owner = policy.lever_owner(cfg, lever)
            approval = policy.lever_approval(cfg, lever)
            driver = re.sub(r"^\s*H\d+\s*[:.\-]\s*", "", a.get("driver", "") or "—")
            with col, st.container(border=True):
                st.markdown(f"**{a.get('action', '')}**")
                st.markdown(
                    row("① driver", driver)
                    + row("② controllable lever", lever)
                    + row("③ action", a.get("action", "—"))
                    + row("④ expected impact", a.get("expected_impact", "—"))
                    + row("⑤ Owner · Decision right", f"{owner} : {approval}")
                    + row("⑥ confidence", a.get("confidence", "—"))
                    + row("⑦ monitoring plan", a.get("monitoring", "—")),
                    unsafe_allow_html=True)
