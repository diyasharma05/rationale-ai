"""Rationale.AI : V1 prototype UI (Accenture Innovation Challenge Round 2).

Run:  streamlit run app.py
"""
import os
import re
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml

import feedback as fb
import telemetry
from engine import anomaly, confidence, db, pyramid, stats_ml
from llm import prompts
from llm.client import HAIKU, LLMClient

# Grafana-style analysis window: any complete month with >= 6 months of history.
# The engine is fully parameterized on period : picking a month recomputes
# everything live (anomalies, contributions, drivers, forecasts).
PERIODS = ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
DEFAULT_PERIOD = "2026-07"
PERIOD = st.session_state.get("period", DEFAULT_PERIOD)


def month_name(p):
    return pd.Period(p, freq="M").strftime("%B %Y")

st.set_page_config(page_title="Rationale.AI", page_icon="🧭", layout="wide")


# --- validated reference palette (dataviz method), theme-aware ---
def _theme_base():
    """Single source of truth: the sidebar toggle (session), else server config."""
    if "dark_mode" in st.session_state:
        return "dark" if st.session_state["dark_mode"] else "light"
    try:
        from streamlit import config as _cfg
        if _cfg.get_option("theme.base") in ("light", "dark"):
            return _cfg.get_option("theme.base")
    except Exception:
        pass
    return "dark"


_PALETTES = {
    # Accenture brand theme: core purple #A100FF on white; lighter purple steps on
    # black for dark mode. Status colors (good/warning/critical) stay reserved and
    # unthemed per the dataviz method; *_text variants are contrast-passing steps
    # of the same hue for small text (all ratios verified >= 4.5:1 per surface).
    "light": {
        "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#6e6c66",
        "grid": "#eae6f2", "axis": "#cbc4d9",
        "panel": "#faf7fd", "border": "rgba(70,0,115,0.12)",
        "chip": "rgba(70,0,115,0.05)",
        "band": "rgba(137,129,145,0.20)",           # threshold band (neutral)
        "series": "#a100ff", "series_text": "#7500c0", "fill": "rgba(161,0,255,0.10)",
        "pos": "#a100ff", "neg": "#d03b3b",         # diverging poles (purple <-> red)
        "good": "#0ca30c", "critical": "#d03b3b", "warning": "#fab219",
        "good_text": "#006300", "critical_text": "#b02a2a", "warning_text": "#8a5a00",
        "llm": "#b13268",                           # magenta, distinct from brand purple
    },
    "dark": {
        "ink": "#ffffff", "ink2": "#c9c3d1", "muted": "#8f8899",
        "grid": "#2b2731", "axis": "#3a3542",
        "panel": "rgba(180,85,240,0.055)", "border": "rgba(190,130,255,0.14)",
        "chip": "rgba(255,255,255,0.06)",
        "band": "rgba(255,255,255,0.07)",
        "series": "#b455f0", "series_text": "#be82ff", "fill": "rgba(180,85,240,0.16)",
        "pos": "#b455f0", "neg": "#e66767",         # dark-stepped diverging poles
        "good": "#0ca30c", "critical": "#d03b3b", "warning": "#fab219",
        "good_text": "#0ca30c", "critical_text": "#e66767", "warning_text": "#fab219",
        "llm": "#e87ba4",                           # magenta, distinct from brand purple
    },
}
_BASE = _theme_base()
C = _PALETTES[_BASE]

# Theme the app shell directly with CSS so the toggle takes effect instantly,
# regardless of when Streamlit's own chrome catches up.
_SHELL = {"dark": {"page": "#0d0d0d", "side": "#171320"},
          "light": {"page": "#ffffff", "side": "#f5f0fa"}}[_BASE]
st.markdown(f"""<style>
  .stApp {{ background-color: {_SHELL['page']}; color: {C['ink']}; }}
  [data-testid="stHeader"] {{ background-color: {_SHELL['page']}; }}
  [data-testid="stSidebar"] {{ background-color: {_SHELL['side']}; }}
  [data-testid="stSidebar"] * {{ color: {C['ink2']}; }}
  [data-testid="stSidebar"] h1 {{ color: {C['ink']}; }}
  .stApp h1, .stApp h2, .stApp h3, .stApp h4 {{ color: {C['ink']}; }}
  .stApp p, .stApp li, .stApp label {{ color: {C['ink']}; }}
  [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {{
      color: {C['muted']} !important; }}
  [data-testid="stMetricValue"] {{ color: {C['ink']}; }}
  [data-testid="stMetricLabel"] * {{ color: {C['muted']}; }}
  [data-testid="stExpander"] details {{ border-color: {C['border']}; }}
  /* sidebar nav reads as bold menu entries */
  [data-testid="stSidebar"] .stRadio label p {{
      font-weight: 700; font-size: 1.02rem; }}
  /* tab labels read as section headers */
  .stTabs button[data-baseweb="tab"] p {{
      font-size: 0.92rem; font-weight: 700; letter-spacing: .04em;
      text-transform: uppercase; }}
  /* selectbox dropdown renders in a body-level portal, outside .stApp : theme it too */
  div[data-baseweb="popover"] ul[data-baseweb="menu"] {{
      background-color: {_SHELL['side']} !important; border: 1px solid {C['border']}; }}
  div[data-baseweb="popover"] ul[data-baseweb="menu"] li[role="option"] {{
      color: {C['ink']} !important; background-color: transparent; }}
  div[data-baseweb="popover"] ul[data-baseweb="menu"] li[role="option"]:hover,
  div[data-baseweb="popover"] ul[data-baseweb="menu"] li[aria-selected="true"] {{
      background-color: {C['band']} !important; }}
</style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------- helpers
def fmt(v, unit):
    return pyramid._fmt_value(v, unit)


def monthly_impact(an, unit):
    if unit != "INR/day" or an.get("current") is None or an.get("mean") is None:
        return None
    return (an["current"] - an["mean"]) * 30


def badge(text, color):
    return f"<span style='color:{color};font-weight:600;font-size:0.85rem'>{text}</span>"


def human_line(cfg, an):
    """One plain-English sentence about a KPI : templated from the numbers, no LLM."""
    name = cfg["name"].split(" (")[0]
    if an["sparse"]:
        return (f"{name} is new : only {an['n_history']} month(s) of history so far, "
                f"so we're watching it rather than judging it.")
    val, usual = fmt(an["current"], cfg["unit"]), fmt(an["mean"], cfg["unit"])
    direction = "up" if (an["z"] or 0) > 0 else "down"
    if an["material"]:
        imp = monthly_impact(an, cfg["unit"])
        tail = (f" If it holds, that's about {fmt(imp, 'INR')} a month."
                if imp is not None else "")
        return (f"{name} came in at {val} : {direction} about "
                f"{abs(an['pct_vs_recent']):.0f}% from its usual {usual}. That's well outside "
                f"its normal range, which is why it's flagged.{tail}")
    return (f"{name} is at {val}, close to its usual {usual} : moving around, "
            "but nothing unusual.")


def pill(text, role):
    """role is a palette key ('good'/'warning'/'critical'/'ink2'/...): the accent color
    draws the tint + border; the *_text variant (when defined) carries the label so
    small text passes contrast on both surfaces."""
    accent = C.get(role, role)
    txt = C.get(f"{role}_text", accent)
    return (f"<span style='background:{accent}22;color:{txt};border:1px solid {accent};"
            f"border-radius:10px;padding:1px 8px;font-size:0.78rem;font-weight:600'>{text}</span>")


def base_layout(fig, height):
    fig.update_layout(
        height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=8, b=8), showlegend=False,
        font=dict(color=C["ink2"], size=11),
        hoverlabel=dict(font_size=12),
    )
    fig.update_xaxes(showgrid=False, linecolor=C["axis"], tickcolor=C["axis"])
    fig.update_yaxes(gridcolor=C["grid"], zerolinecolor=C["axis"], linecolor=C["axis"])
    return fig


def sparkline(series, an, cfg, height=150):
    """Grafana-style trend panel: area line, normal-range band (the actual signal-gate
    threshold: mean ± min_abs_z·σ), dashed baseline, the analysis month marked, and a
    dotted 3-month OLS forecast with its 90% prediction interval (non-LLM)."""
    x, y = list(series["period"]), [float(v) for v in series["value"]]
    fig = go.Figure()
    lo_all, hi_all = list(y), list(y)

    # 3-month OLS trend forecast (computed before layout so the range includes it)
    fc, fx = None, []
    if not an["sparse"] and len(y) >= 7:
        fc = stats_ml.ols_forecast(y, horizon=3)
        last_p = pd.Period(x[-1], freq="M")
        fx = [x[-1]] + [str(last_p + i) for i in range(1, 4)]
        lo_all += fc["lo"]
        hi_all += fc["hi"]

    if not an["sparse"] and an.get("mean") is not None and an.get("std"):
        zt = cfg["materiality"]["min_abs_z"]
        up, lo = an["mean"] + zt * an["std"], an["mean"] - zt * an["std"]
        lo_all += [lo]
        hi_all += [up]
        bx = x + fx[1:]
        fig.add_trace(go.Scatter(x=bx, y=[up] * len(bx), mode="lines",
                                 line=dict(width=0), hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=bx, y=[lo] * len(bx), mode="lines", line=dict(width=0),
                                 fill="tonexty", fillcolor=C["band"], hoverinfo="skip",
                                 name="normal range"))
        fig.add_trace(go.Scatter(x=bx, y=[an["mean"]] * len(bx), mode="lines",
                                 line=dict(color=C["muted"], width=1, dash="dot"),
                                 hoverinfo="skip"))
    ymin, ymax = min(lo_all), max(hi_all)
    pad = (ymax - ymin) * 0.12 or 1
    floor = ymin - pad
    fig.add_trace(go.Scatter(x=x, y=[floor] * len(x), mode="lines",
                             line=dict(width=0), hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="lines", line=dict(color=C["series"], width=2),
        fill="tonexty", fillcolor=C["fill"],
        hovertemplate="%{x} · %{y:,.1f}<extra></extra>"))
    if fc:
        fig.add_trace(go.Scatter(x=fx, y=[y[-1]] + fc["hi"], mode="lines",
                                 line=dict(width=0), hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=fx, y=[y[-1]] + fc["lo"], mode="lines",
                                 line=dict(width=0), fill="tonexty", fillcolor=C["fill"],
                                 hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=fx, y=[y[-1]] + fc["pred"], mode="lines",
                                 line=dict(color=C["series"], width=2, dash="dot"),
                                 hovertemplate="%{x} · %{y:,.1f}<extra>OLS trend forecast</extra>"))
    if PERIOD in set(x):
        cur = series[series["period"] == PERIOD]
        flagged = bool(an.get("material"))
        fig.add_trace(go.Scatter(
            x=cur["period"], y=cur["value"], mode="markers",
            marker=dict(size=10, color=C["critical"] if flagged else C["series"],
                        line=dict(width=2, color=C["ink"] if flagged else C["axis"])),
            hovertemplate="%{x} · %{y:,.1f}"
                          + ("<extra>outside normal range</extra>" if flagged
                             else "<extra>analysis month</extra>")))
    base_layout(fig, height)
    fig.update_yaxes(visible=False, range=[floor, ymax + pad])
    fig.update_xaxes(tickvals=[x[0], PERIOD] + (fx[-1:] if fx else []),
                     tickfont=dict(size=10, color=C["muted"]))
    return fig


def stat_tile(label, value, delta_txt=None, delta_color=None, chip=None, sub=None,
              accent=None):
    """Redash-style metric counter: label, hero number, delta pill, context line."""
    accent = accent or C["border"]
    bits = [
        f"<div style='font-size:0.72rem;color:{C['muted']};text-transform:uppercase;"
        f"letter-spacing:.06em;margin-bottom:2px'>{label}</div>",
        f"<div style='font-size:1.65rem;font-weight:750;color:{C['ink']};line-height:1.15'>{value}</div>",
    ]
    row = []
    if delta_txt:
        row.append(f"<span style='color:{delta_color or C['ink2']};font-weight:700;"
                   f"font-size:0.9rem'>{delta_txt}</span>")
    if chip:
        row.append(f"<span style='background:{C['chip']};border:1px solid {C['border']};"
                   f"border-radius:9px;padding:0 7px;font-size:0.72rem;color:{C['ink2']}'>{chip}</span>")
    if row:
        bits.append("<div style='margin-top:2px'>" + " ".join(row) + "</div>")
    if sub:
        bits.append(f"<div style='font-size:0.74rem;color:{C['muted']};margin-top:3px'>{sub}</div>")
    return (f"<div style='border:1px solid {C['border']};border-left:4px solid {accent};"
            f"border-radius:10px;padding:10px 14px;background:{C['panel']};"
            f"min-height:96px'>{''.join(bits)}</div>")


def delta_bar(table, unit, height=260, bad_when="down"):
    """bad_when: which direction is BAD for this KPI ('down' for revenue-like,
    'up' for complaint-like) : bad movement renders red, good renders brand purple."""
    t = table.head(6).iloc[::-1]
    is_bad = (lambda d: d > 0) if bad_when == "up" else (lambda d: d < 0)
    colors = [C["neg"] if is_bad(d) else C["pos"] for d in t["delta"]]
    fig = go.Figure(go.Bar(
        x=t["delta"], y=t["member"].astype(str), orientation="h",
        marker=dict(color=colors), text=[fmt(d, unit) for d in t["delta"]],
        textposition="outside", cliponaxis=False,
        customdata=(t["share_of_delta"] * 100).round(0),
        hovertemplate="%{y}: %{x:,.1f} (%{customdata}% of total movement)<extra></extra>"))
    base_layout(fig, height)
    fig.update_layout(bargap=0.35, margin=dict(l=8, r=70, t=8, b=8))
    fig.update_xaxes(title="Δ vs trailing-3-month baseline", title_font=dict(size=10))
    return fig


def confidence_gauge(conf, height=96):
    """Bullet gauge: confidence fill vs the two decision gates drawn as thresholds."""
    v = conf["value"]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=[1.0], y=[""], orientation="h", marker_color=C["band"],
                         hoverinfo="skip"))
    fig.add_trace(go.Bar(x=[v], y=[""], orientation="h", marker_color=C["series"],
                         text=[f"{v:.0%}"], textposition="auto",
                         textfont=dict(color=C["ink"], size=13),
                         hovertemplate=f"confidence {v:.2f}<extra></extra>"))
    for gate, label in ((confidence.EVIDENCE_GATE, "evidence gate"),
                        (confidence.ACTION_GATE, "action gate")):
        fig.add_shape(type="line", x0=gate, x1=gate, y0=-0.45, y1=0.45,
                      line=dict(color=C["ink2"], width=1.5, dash="dash"))
        fig.add_annotation(x=gate, y=0.62, text=label, showarrow=False,
                           font=dict(size=9, color=C["muted"]))
    base_layout(fig, height)
    fig.update_layout(barmode="overlay", margin=dict(l=8, r=8, t=18, b=8))
    fig.update_xaxes(range=[0, 1.0], tickvals=[0, 0.5, 1.0],
                     tickformat=".0%", tickfont=dict(size=9, color=C["muted"]))
    fig.update_yaxes(visible=False)
    return fig


def confidence_components(conf, height=118):
    """Why the confidence is what it is: the three weighted ingredients."""
    comps, w = conf["components"], conf["weights"]
    order = ["evidence", "coverage", "signal"]
    labels = {"signal": "signal strength", "coverage": "driver coverage",
              "evidence": "evidence agreement"}
    fig = go.Figure(go.Bar(
        x=[comps[k] for k in order], y=[labels[k] for k in order], orientation="h",
        marker_color=C["fill"], marker_line=dict(color=C["series"], width=1),
        text=[f"{comps[k]:.2f}" for k in order], textposition="outside", cliponaxis=False,
        customdata=[w[k] for k in order],
        hovertemplate="%{y}: %{x:.2f} (weight %{customdata})<extra></extra>"))
    base_layout(fig, height)
    fig.update_layout(margin=dict(l=8, r=36, t=6, b=6))
    fig.update_xaxes(range=[0, 1.12], visible=False)
    fig.update_yaxes(tickfont=dict(size=10, color=C["ink2"]))
    return fig


def contribution_waterfall(table, unit, height=290):
    """Baseline → per-member deltas → current: the classic 'where did it go' visual.
    Only for additive KPIs (sums are meaningful)."""
    t = table.sort_values("delta", key=lambda s: s.abs(), ascending=False).head(6)
    base_total, cur_total = float(table["baseline"].sum()), float(table["current"].sum())
    fig = go.Figure(go.Waterfall(
        x=["3-mo baseline"] + list(t["member"].astype(str)) + ["this month"],
        y=[base_total] + list(t["delta"]) + [0],
        measure=["absolute"] + ["relative"] * len(t) + ["total"],
        decreasing=dict(marker=dict(color=C["critical"])),
        increasing=dict(marker=dict(color=C["pos"])),
        totals=dict(marker=dict(color=C["axis"])),
        connector=dict(line=dict(color=C["grid"], width=1)),
        text=[fmt(base_total, unit)] + [fmt(d, unit) for d in t["delta"]] + [fmt(cur_total, unit)],
        textposition="outside", textfont=dict(size=10),
        hovertemplate="%{x}: %{text}<extra></extra>"))
    base_layout(fig, height)
    fig.update_layout(margin=dict(l=8, r=8, t=28, b=8))
    fig.update_yaxes(visible=False)
    fig.update_xaxes(tickfont=dict(size=10, color=C["ink2"]))
    return fig


def hypothesis_bars(hyps, height=None):
    """Ranked explanatory drivers as bars: length = computed strength, color =
    corroborated (brand) vs uncorroborated (gray)."""
    hs = sorted(hyps, key=lambda h: h.get("rank", 99))
    contract = db.load_contract()["kpis"]

    def short(h):
        if h.get("driver_id") in contract:
            return contract[h["driver_id"]]["name"].split(" (")[0]
        lbl = re.sub(r"^\s*H\d+\s*[:.\-]\s*", "", h["label"])
        return (lbl[:34] + "…") if len(lbl) > 35 else lbl

    def etext(h):
        parts = ([f"{len(h['snippets'])} docs"] if h["snippets"] else []) \
              + (["market event"] if h["events"] else [])
        return " + ".join(parts) or "UNCORROBORATED"

    names = [f"{h.get('rank', '?')}. {short(h)}" for h in hs][::-1]
    vals = [h.get("strength", 0) for h in hs][::-1]
    corro = [bool(h["snippets"] or h["events"]) for h in hs][::-1]
    colors = [C["series"] if c else C["axis"] for c in corro]
    texts = [etext(h) for h in hs][::-1]
    fig = go.Figure(go.Bar(
        x=vals, y=names, orientation="h", marker_color=colors,
        text=texts, textposition="outside", cliponaxis=False,
        textfont=dict(size=10),
        hovertemplate="%{y}<br>strength %{x:.2f} · %{text}<extra></extra>"))
    base_layout(fig, height or (70 + 44 * len(hs)))
    fig.update_layout(bargap=0.42, margin=dict(l=8, r=110, t=6, b=6))
    fig.update_xaxes(range=[0, 1.05], visible=False)
    fig.update_yaxes(tickfont=dict(size=11, color=C["ink"]))
    return fig


def gate_bullets(an, cfg, height=118):
    """How far past the signal gate each materiality test landed: bar length is
    the measured value as a multiple of its own threshold (dashed line = gate)."""
    m = cfg["materiality"]
    rows = [("% change", abs(an["pct_vs_recent"] or 0), m["min_pct"],
             f"{abs(an['pct_vs_recent'] or 0):.1f}%"),
            ("z-score", abs(an["z"] or 0), m["min_abs_z"],
             f"{abs(an['z'] or 0):.2f}")]
    ratios = [min(v / max(thr, 1e-9), 3.0) for _, v, thr, _ in rows]
    colors = [C["critical"] if v >= thr else C["axis"] for _, v, thr, _ in rows]
    fig = go.Figure(go.Bar(
        x=ratios, y=[r[0] for r in rows], orientation="h", marker_color=colors,
        text=[r[3] for r in rows], textposition="outside", cliponaxis=False,
        textfont=dict(size=11),
        hovertemplate="%{y}: %{text} : the dashed line is this test's gate<extra></extra>"))
    fig.add_shape(type="line", x0=1, x1=1, y0=-0.5, y1=1.5,
                  line=dict(color=C["ink2"], width=1.5, dash="dash"))
    fig.add_annotation(x=1, y=1.75, text="gate", showarrow=False,
                       font=dict(size=9, color=C["muted"]))
    base_layout(fig, height)
    fig.update_layout(bargap=0.45, margin=dict(l=8, r=54, t=16, b=6))
    fig.update_xaxes(range=[0, max(ratios) * 1.18 + 0.1], visible=False)
    fig.update_yaxes(tickfont=dict(size=10, color=C["ink2"]))
    return fig


@st.cache_resource
def get_llm():
    return LLMClient()


def scan_kpis(role_id):
    out = {}
    for kpi_id, cfg in db.allowed_kpis(role_id).items():
        s = db.kpi_series(kpi_id, role_id)
        an = anomaly.analyze(s, PERIOD, cfg["materiality"], cfg.get("min_history", 6))
        out[kpi_id] = (cfg, s, an)
    return out


def severity_order(scan):
    """Objective 1: prioritise material movements : flagged first, worst first."""
    def key(item):
        _, (cfg, s, an) = item
        if an["material"]:
            return (0, -abs(an["z"] or 0))
        if an["sparse"]:
            return (1, 0)
        return (2, 0)
    return [k for k, _ in sorted(scan.items(), key=key)]


def section_label(text):
    """Grafana-style row label: small, uppercase, muted."""
    st.markdown(f"<div style='font-size:0.78rem;color:{C['muted']};text-transform:uppercase;"
                f"letter-spacing:.08em;margin:16px 0 6px'>{text}</div>",
                unsafe_allow_html=True)


# how each analytical method is badged throughout the app
METHODS = {
    "sql": ("SQL", "series"),
    "stats": ("statistics", "good"),
    "ml": ("ML", "warning"),
    "retrieval": ("retrieval", "ink2"),
    "rules": ("rules", "ink2"),
    "llm": ("LLM · words only", "llm"),
}


def method_chip(kind, text=None):
    label, _role = METHODS[kind]
    return (f"<span style='background:{C['chip']};color:{C['ink2']};"
            f"border:1px solid {C['border']};"
            f"border-radius:9px;padding:1px 8px;font-size:0.74rem;font-weight:600;"
            f"margin-right:6px'>{text or label}</span>")


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
    st.markdown(f"<div style='font-size:0.72rem;color:{C['muted']};text-transform:uppercase;"
                f"letter-spacing:.06em;margin-top:8px'>What built this answer</div>",
                unsafe_allow_html=True)
    method_chip_row(kinds, texts)


SYNONYMS = {"sales": "revenue", "money": "revenue", "income": "revenue",
            "deliveries": "delivery", "shipping": "delivery", "late": "sla",
            "clients": "accounts", "customers": "customer", "churn": "churn",
            "ads": "marketing", "leads": "conversion", "basket": "basket"}


def match_kpi(question, kpis):
    """Plain-English question -> KPI id. Deterministic keyword scoring first;
    a live Haiku fallback handles phrasing the keywords miss."""
    toks = [SYNONYMS.get(t, t) for t in re.findall(r"[a-z]+", question.lower())]
    scores = {}
    for kpi_id, cfg in kpis.items():
        name_toks = set(re.findall(r"[a-z]+", cfg["name"].lower()))
        tag_toks = set(t.lower() for t in cfg.get("tags", []))
        scores[kpi_id] = sum(3 for t in toks if t in name_toks) + \
                         sum(1 for t in toks if t in tag_toks)
    best = max(scores, key=scores.get)
    ranked = sorted(scores.values(), reverse=True)
    if scores[best] > 0 and (len(ranked) < 2 or ranked[0] > ranked[1]):
        return best, "keyword match"
    return None, None


def lever_approval(cfg, lever_text):
    for l in cfg.get("levers", []):
        if l["lever"] == lever_text or l["lever"] in lever_text or lever_text in l["lever"]:
            return l.get("approval", "—")
    return "—"


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
                        f"{a.get('owner', '—')} : {lever_approval(cfg, a.get('lever', ''))}")
                    + row("Expected impact", a.get("expected_impact", "—"))
                    + row("How we'll know it's working", a.get("monitoring", "—")),
                    unsafe_allow_html=True)


# ---------------------------------------------------------------- sidebar
if "_nav_target" in st.session_state:
    st.session_state.nav = st.session_state.pop("_nav_target")
if "investigations" not in st.session_state:
    st.session_state.investigations = {}

with st.sidebar:
    st.markdown(
        f"<div style='font-size:2.35rem;font-weight:800;letter-spacing:-0.02em;"
        f"line-height:1.1;padding:4px 0 2px;color:{C['ink']}'>"
        f"Rationale<span style='color:{C['series']}'>.AI</span></div>",
        unsafe_allow_html=True)
    st.caption("Confidence-driven KPI intelligence-to-action engine : Team Rational.ai")
    if "dark_mode" not in st.session_state:
        st.session_state.dark_mode = (_BASE == "dark")
    st.toggle("🌙 Dark mode", key="dark_mode")
    _desired = "dark" if st.session_state.dark_mode else "light"
    try:
        from streamlit import config as _st_config
        if _st_config.get_option("theme.base") != _desired:
            _st_config.set_option("theme.base", _desired)
            # Accenture purple, stepped per mode (replaces stock Streamlit red accents)
            _st_config.set_option("theme.primaryColor",
                                  "#a100ff" if _desired == "light" else "#b455f0")
            st.rerun()   # native widgets pick the new theme up on the rerun
    except Exception:
        pass
    roles = db.load_roles()
    role_id = st.selectbox("Signed in as (role)", list(roles), key="role_sel",
                           format_func=lambda r: roles[r]["label"])
    persona = roles[role_id]["persona"]
    is_exec = persona == "executive"
    st.caption(f"Row access: **{'all regions' if roles[role_id]['regions'] == 'all' else ', '.join(roles[role_id]['regions'])}** · "
               f"Account names: **{'masked' if roles[role_id]['mask_accounts'] else 'visible'}**")
    nav = st.radio("View", ["Dashboard", "Data", "Investigation", "Decision Ledger",
                            "Under the Hood"],
                   key="nav", label_visibility="collapsed")
    st.divider()
    llm = get_llm()
    st.markdown("".join(method_chip(k) for k in ("sql", "stats", "ml", "llm")),
                unsafe_allow_html=True)
    st.caption("The engine is SQL + statistics + ML first; the LLM only writes language.")
    with st.expander("LLM settings"):
        st.caption("Mode: **" + ("Live : Claude API" if llm.mode == "live"
                                 else "Offline : cached responses (no key needed)") + "**")
        key_in = st.text_input("Anthropic API key", type="password",
                               placeholder="sk-ant-…", key="api_key_input",
                               help="Held in memory for this session only — never written "
                                    "to disk. If the key is invalid, the app quietly falls "
                                    "back to offline responses.")
        kc1, kc2 = st.columns(2)
        if kc1.button("Use this key", key="apply_key", width="stretch"):
            if key_in.strip():
                os.environ["ANTHROPIC_API_KEY"] = key_in.strip()
                os.environ.pop("MOCK_MODE", None)
                get_llm.clear()
                st.rerun()
        if llm.mode == "live" and kc2.button("Go offline", key="clear_key", width="stretch"):
            os.environ["MOCK_MODE"] = "1"
            get_llm.clear()
            st.rerun()
    if st.button("↺ Reset demo state"):
        fb.reset_ledger()
        st.session_state.investigations = {}
        telemetry.RECORDS.clear()
        st.success("Ledger, feedback and cached investigations reset.")

# ---- top control bar (Grafana-style): analysis window, top right ----
if nav in ("Dashboard", "Data", "Investigation"):
    if "period" not in st.session_state:
        st.session_state.period = DEFAULT_PERIOD
    _tb_left, _tb_right = st.columns([3.2, 1.1])
    with _tb_right:
        PERIOD = st.selectbox("Analysis window", PERIODS, key="period",
                              format_func=lambda p: month_name(p)
                              + ("  · latest" if p == DEFAULT_PERIOD else ""))
    with _tb_left:
        st.caption("")  # spacer keeps the picker on the baseline
        st.markdown(f"<div style='color:{C['muted']};font-size:0.85rem;padding-top:26px'>"
                    f"analysing <b style='color:{C['ink']}'>{month_name(PERIOD)}</b> : every "
                    f"number on this page is computed live for this window</div>",
                    unsafe_allow_html=True)

# ---------------------------------------------------------------- dashboard
if nav == "Dashboard":
    _t0 = time.perf_counter()
    scan = scan_kpis(role_id)
    _scan_ms = (time.perf_counter() - _t0) * 1000
    kpi_ids = severity_order(scan)
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
                   f"range · ≈ **{fmt(total_imp, 'INR')}/month** at stake · sharpest mover: "
                   f"**{lead}**. Signed in as **{roles[role_id]['label']}**.")
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
                        st.plotly_chart(sparkline(s, an, cfg, height=120), width="stretch",
                                        config={"displayModeBar": False}, key=f"pop_spark_{k}")
                        if st.button("🔍 Investigate why", key=f"pop_inv_{k}", type="primary",
                                     width="stretch"):
                            st.session_state.kpi_sel = k
                            st.session_state._nav_target = "Investigation"
                            st.session_state._autorun = True
                            st.rerun()

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
                st.markdown(f"<div style='font-size:1.6rem;font-weight:750;color:{C['ink']};"
                            f"line-height:1.2'>{fmt(an['current'], cfg['unit'])}{delta_html}</div>",
                            unsafe_allow_html=True)
                imp = monthly_impact(an, cfg["unit"])
                st.caption(f"≈ {fmt(imp, 'INR')} /month vs baseline" if an["material"] and imp is not None
                           else f"{cfg['name'].split(' (')[0]} · monthly · {db.load_contract()['sources'][cfg['source']]['system'].split(' (')[0]}")
                st.plotly_chart(sparkline(s, an, cfg), width="stretch",
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
                    st.session_state.kpi_sel = kpi_id
                    st.session_state._nav_target = "Investigation"
                    st.session_state._autorun = True
                    st.rerun()

# ---------------------------------------------------------------- data explorer
elif nav == "Data":
    st.header("Data : the live feed behind every number")
    st.caption("Redash-style explorer over the governed sources. Every query below runs "
               "against the same tables the engine reads, with this role's row-level "
               "security applied : nothing is precomputed.")

    _DATE_COLS = {"sales_orders": "order_date", "ops_fulfilment": "ship_date",
                  "crm_events": "event_date", "marketing_weekly": "week_start"}
    fresh = db.source_freshness()
    c1, c2, c3 = st.columns([2, 1, 2])
    src = c1.selectbox("Source", list(_DATE_COLS),
                       format_func=lambda s: f"{fresh[s]['system']}  ·  {s}")
    grain = c2.radio("Grain", ["day", "week", "month"], index=2, horizontal=True)
    dmin, dmax = pd.Timestamp("2025-08-01").date(), pd.Timestamp(fresh[src]["as_of"]).date()
    drange = c3.slider("Time range", min_value=dmin, max_value=dmax, value=(dmin, dmax),
                       format="YYYY-MM-DD")

    col = _DATE_COLS[src]
    where = db.role_where(role_id)
    vol_sql = (f"SELECT date_trunc('{grain}', CAST({col} AS DATE)) AS bucket, COUNT(*) AS rows_ "
               f"FROM {src} WHERE CAST({col} AS DATE) BETWEEN DATE '{drange[0]}' "
               f"AND DATE '{drange[1]}'{where} GROUP BY 1 ORDER BY 1")
    t0 = time.perf_counter()
    vol = db.get_conn().execute(vol_sql).fetchdf()
    latest = db.get_conn().execute(
        f"SELECT * FROM {src} WHERE CAST({col} AS DATE) BETWEEN DATE '{drange[0]}' "
        f"AND DATE '{drange[1]}'{where} ORDER BY CAST({col} AS DATE) DESC LIMIT 50").fetchdf()
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

# ---------------------------------------------------------------- investigation
elif nav == "Investigation":
    st.header("Investigation")
    kpis = db.allowed_kpis(role_id)
    ids = list(kpis)

    # --- ask in plain English (LLM-assisted intent understanding) ---
    q = st.text_input("Ask a question in plain English", key="ask_box",
                      placeholder='e.g. "Why did revenue fall in July?" or "What happened to complaints?"')
    if q:
        matched, how = match_kpi(q, kpis)
        if matched is None and llm.mode == "live":
            data = llm.json_call("intent", prompts.INTENT_SYSTEM,
                                 f"KPIs: {[(k, kpis[k]['name']) for k in ids]}\nQuestion: {q}",
                                 model=HAIKU, max_tokens=300)
            if data and data.get("kpi_id") in ids:
                matched, how = data["kpi_id"], "Claude intent"
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
    run = c1.button("▶ Run investigation", type="primary", key="run_btn") \
        or st.session_state.pop("_autorun", False)
    if c2.button("Re-run (ignore cache)", key="rerun_btn"):
        st.session_state.investigations.pop(key, None)
        run = True
    if run and key not in st.session_state.investigations:
        with st.spinner("🧭 Investigation in progress…", show_time=True):
            result = pyramid.investigate(kpi_id, PERIOD, role_id, llm)
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
        }[r["outcome"]]

        # ---- verdict row: the metric's own chart + the decision, side by side ----
        section_label("The verdict")
        vL, vR = st.columns([3, 2])
        with vL:
            st.plotly_chart(sparkline(r["series"], an, cfg, height=252), width="stretch",
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
            if r["unit"] in ("INR/day", "INR", "accounts"):
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
                        and an.get("z") is not None:
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
            if fc1.button("👍 Correct", key=f"up_{r['inv_id']}"):
                fb.log_feedback(r["inv_id"], "up", comment)
                st.toast("Logged : confirmed conclusions strengthen future Recall.", icon="✅")
            if fc2.button("👎 Wrong", key=f"dn_{r['inv_id']}"):
                fb.log_feedback(r["inv_id"], "down", comment)
                st.toast("Logged : future related investigations will retrieve this correction.",
                         icon="📝")

# ---------------------------------------------------------------- ledger
elif nav == "Decision Ledger":
    st.header("Decision Ledger")
    st.caption("Every investigation, conclusion, confidence score and user correction is appended "
               "here. Past-period entries are part of the Level-2 retrieval corpus, so the engine "
               "recalls precedent : the RECALL step and the learning loop.")
    entries = fb.read_ledger()
    if entries:
        df = pd.DataFrame(entries)[::-1]
        st.dataframe(df[["id", "timestamp", "kpi", "period", "outcome", "confidence", "summary"]],
                     hide_index=True, width="stretch", height=420)
    else:
        st.info("Ledger empty : run an investigation.")

# ---------------------------------------------------------------- under the hood
elif nav == "Under the Hood":
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

    st.subheader("Cumulative session telemetry")
    if telemetry.RECORDS:
        st.dataframe(pd.DataFrame(telemetry.RECORDS)[["task", "model", "mode", "latency_ms",
                                                      "input_tokens", "output_tokens", "cost_usd", "cost_inr"]],
                     hide_index=True, height=260)
        s = telemetry.summarize(telemetry.RECORDS)
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
    kpi_pick = st.selectbox("KPI", list(contract["kpis"]),
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
