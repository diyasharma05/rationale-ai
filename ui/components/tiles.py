"""Small HTML fragments: badges, state pills, stat tiles, section headers."""

import streamlit as st

from ui.theme import C, FONT_MONO


def badge(text, color):
    return f"<span style='color:{color};font-weight:600;font-size:0.85rem'>{text}</span>"


# Deterministic prose lives with the other deterministic prose
# (llm/fallback.py), next to template_narrative.


def pill(text, role):
    """State indicator : a colored square glyph + sentence-case word in ink.
    Deliberately not a capsule — state reads like an instrument lamp, and the
    color never has to carry the text's contrast."""
    accent = C.get(role, role)
    return (f"<span style='white-space:nowrap'><span style='color:{accent};"
            f"font-size:0.7rem'>▪</span> <span style='color:{C['ink2']};"
            f"font-size:0.8rem;font-weight:600'>{text}</span></span>")


def stat_tile(label, value, delta_txt=None, delta_color=None, chip=None, sub=None,
              accent=None):
    """Instrument tile: sentence-case label, mono numeral, plain-text context.
    No left stripes, no capsules — a 2px top rule appears ONLY when the tile is
    in an alarm/watch state (accent = critical/warning); everything else is quiet."""
    top = (f"border-top:2px solid {accent};"
           if accent in (C["critical"], C["warning"]) else "")
    bits = [
        f"<div style='font-size:0.8rem;font-weight:500;color:{C['muted']};"
        f"margin-bottom:2px'>{label}</div>",
        f"<div style='font-family:{FONT_MONO};font-size:1.5rem;font-weight:500;"
        f"font-variant-numeric:tabular-nums;color:{C['ink']};line-height:1.2'>{value}</div>",
    ]
    row = []
    if delta_txt:
        row.append(f"<span style='color:{delta_color or C['ink2']};font-weight:600;"
                   f"font-size:0.84rem'>{delta_txt}</span>")
    if chip:
        row.append(f"<span style='font-family:{FONT_MONO};font-size:0.72rem;"
                   f"color:{C['muted']}'>{chip}</span>")
    if row:
        bits.append("<div style='margin-top:3px;display:flex;gap:10px;align-items:baseline'>"
                    + " ".join(row) + "</div>")
    if sub:
        bits.append(f"<div style='font-size:0.75rem;color:{C['muted']};margin-top:4px'>{sub}</div>")
    return (f"<div style='border:1px solid {C['border']};{top}"
            f"border-radius:3px;padding:11px 14px;background:{C['panel']};"
            f"min-height:96px'>{''.join(bits)}</div>")


def section_label(text):
    """Section header: sentence case, weight carries the hierarchy — no caps,
    no tracking, no eyebrow chrome."""
    st.markdown(f"<div style='font-size:0.97rem;font-weight:600;color:{C['ink']};"
                f"margin:20px 0 6px'>{text}</div>", unsafe_allow_html=True)


# how each analytical method is badged throughout the app
