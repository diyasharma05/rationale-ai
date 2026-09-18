"""Plotly figure builders.

Moved from app.py so a chart can be built and inspected without booting
Streamlit. Colours and fonts come from ui.theme. One behavioural change:
sparkline() takes the analysis period as an argument instead of reading a
module global that only existed inside app.py.
"""

import re

import pandas as pd
import plotly.graph_objects as go

from engine import confidence, db, stats_ml
from engine.economics import fmt_value as fmt
from ui.theme import C, FONT_MONO


def base_layout(fig, height):
    fig.update_layout(
        height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=8, b=8), showlegend=False,
        font=dict(color=C["ink2"], size=11, family="IBM Plex Mono, Consolas, monospace"),
        hoverlabel=dict(font_size=12, font_family="IBM Plex Sans, 'Segoe UI', sans-serif"),
    )
    fig.update_xaxes(showgrid=False, linecolor=C["axis"], tickcolor=C["axis"])
    fig.update_yaxes(gridcolor=C["grid"], zerolinecolor=C["axis"], linecolor=C["axis"])
    return fig


def sparkline(series, an, cfg, period, height=150):
    """Trend line with the normal-range band and the analysis month marked.

    `period` is explicit rather than read from a module global: a chart that
    depends on where it is imported cannot be tested or reused."""
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
    if period in set(x):
        cur = series[series["period"] == period]
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
    fig.update_xaxes(tickvals=[x[0], period] + (fx[-1:] if fx else []),
                     tickfont=dict(size=10, color=C["muted"]))
    return fig


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
        customdata=[("" if pd.isna(s) else f" ({s * 100:.0f}% of total movement)")
                    for s in t["share_of_delta"]],
        # the share is omitted for non-additive KPIs (percentages, averages):
        # per-member values do not sum to the national value, so there is no
        # "share of the movement" to quote
        hovertemplate="%{y}: %{x:,.1f}%{customdata}<extra></extra>"))
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
    # A component can be None: this KPI declares no drivers, so coverage was
    # not assessable. Show it as an empty rail rather than a zero bar -- "we
    # could not check this" is a different statement from "this scored zero".
    vals = [comps.get(k) for k in order]
    fig = go.Figure(go.Bar(
        x=[0 if v is None else v for v in vals],
        y=[labels[k] + ("  (not assessable)" if comps.get(k) is None else "")
           for k in order],
        orientation="h",
        marker_color=C["fill"], marker_line=dict(color=C["series"], width=1),
        text=["not assessable" if v is None else f"{v:.2f}" for v in vals],
        textposition="outside", cliponaxis=False,
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
