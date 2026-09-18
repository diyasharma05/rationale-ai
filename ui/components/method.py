"""'What built this answer' — operation counts by method.

Plain mono text rather than capsules: it should read as a spec line. This
is where the claim that the LLM only wrote words is made visible.
"""

import streamlit as st

from ui.theme import C, FONT_MONO


METHODS = {
    "sql": ("SQL", "series"),
    "stats": ("statistics", "good"),
    "ml": ("ML", "warning"),
    "retrieval": ("retrieval", "ink2"),
    "rules": ("rules", "ink2"),
    "llm": ("LLM · words only", "llm"),
}


def method_chip(kind, text=None):
    """Plain mono token, not a capsule — reads like a spec line, not UI chrome."""
    label, _role = METHODS[kind]
    return (f"<span style='font-family:{FONT_MONO};color:{C['ink2']};"
            f"font-size:0.74rem;margin-right:14px;white-space:nowrap'>"
            f"{text or label}</span>")


def method_chip_row(kinds, texts=None):
    chips = "".join(method_chip(k, (texts or {}).get(k)) for k in kinds)
    st.markdown(f"<div style='margin:2px 0 6px'>{chips}</div>", unsafe_allow_html=True)


def method_strip(r):
    """'What built this answer' : operation counts by method, LLM last and
    explicitly words-only. Rendered on every investigation result."""
    mix = r.get("method_mix", {})
    llm_calls = len(r.get("telemetry", []))
    texts = {}
    kinds = []
    if mix.get("sql_queries"):
        kinds.append("sql"); texts["sql"] = f"{mix['sql_queries']} SQL queries"
    if mix.get("stat_tests"):
        kinds.append("stats"); texts["stats"] = f"{mix['stat_tests']} statistical tests"
    if mix.get("ml_models"):
        kinds.append("ml"); texts["ml"] = f"{mix['ml_models']} ML models (IsolationForest)"
    if mix.get("docs_retrieved"):
        kinds.append("retrieval"); texts["retrieval"] = f"{mix['docs_retrieved']} documents retrieved"
    kinds.append("llm")
    texts["llm"] = (f"{llm_calls} LLM calls : words only" if llm_calls
                    else "0 LLM calls : fully deterministic")
    st.markdown(f"<div style='font-size:0.82rem;font-weight:600;color:{C['ink2']};"
                f"margin-top:8px'>What built this answer</div>", unsafe_allow_html=True)
    method_chip_row(kinds, texts)
