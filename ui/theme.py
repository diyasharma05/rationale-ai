"""Theme: palette, fonts, and the global stylesheet.

Extracted verbatim from app.py. Kept as one module because the palette, the
shell colours and the CSS that consumes them have to move together -- a
stylesheet that references a colour the palette no longer defines fails
silently, as a wrong colour rather than an error.
"""
import streamlit as st


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
    # "Chart recorder" system. Data is ink; color carries STATE only:
    #   red       = alarm (breach, flagged, recording lamp)
    #   amber     = watch                                  verdigris = steady/ok
    #   brand purple = the action role (primary buttons, slider, focus) — set via
    #   theme.primaryColor, never used for data or alarms.
    # Surfaces are warm graphite / paper. Every fg/bg pair below is
    # contrast-verified (>=4.5:1 text, >=3:1 marks).
    "light": {   # paper recorder
        "ink": "#20232a", "ink2": "#4b4f55", "muted": "#65696e",
        "grid": "#e3dfd4", "axis": "#c9c4b8",
        "panel": "#fbfaf6", "border": "#d9d4c8",
        "chip": "rgba(32,35,42,0.05)",
        "band": "rgba(110,115,120,0.16)",           # threshold band (neutral)
        "series": "#3a3e45", "series_text": "#20232a", "fill": "rgba(58,62,69,0.10)",
        "pos": "#3f7a5d", "neg": "#b42318",         # polarity = state colors
        "good": "#3f7a5d", "critical": "#b42318", "warning": "#8f6410",
        "good_text": "#3f7a5d", "critical_text": "#9a1f10", "warning_text": "#8f6410",
        "llm": "#65696e",
    },
    "dark": {    # console
        "ink": "#e7e4dc", "ink2": "#b9b5ab", "muted": "#8e959c",
        "grid": "#262a30", "axis": "#31353c",
        "panel": "#1d2025", "border": "#31353c",
        "chip": "rgba(231,228,220,0.05)",
        "band": "rgba(142,149,156,0.14)",
        "series": "#c7c3b8", "series_text": "#e7e4dc", "fill": "rgba(199,195,184,0.10)",
        "pos": "#63a68a", "neg": "#e5484d",
        "good": "#63a68a", "critical": "#e5484d", "warning": "#e0a63c",
        "good_text": "#7fb89e", "critical_text": "#ff7b81", "warning_text": "#e0a63c",
        "llm": "#8e959c",
    },
}
# Bound at import, then REFRESHED IN PLACE by apply() on every run.
#
# app.py used to recompute this at the top of each script execution, so the
# dark-mode toggle simply worked. Moving it into a module froze it at first
# import -- the toggle would have kept flipping Streamlit's own chrome while
# every chart and tile stayed on the palette from whenever this module
# happened to load. Mutating the dict rather than rebinding it means the
# `from ui.theme import C` references scattered through the components stay
# live without any of them needing to know.
_BASE = _theme_base()
C = dict(_PALETTES[_BASE])

# Theme the app shell directly with CSS so the toggle takes effect instantly,
# regardless of when Streamlit's own chrome catches up.
_SHELLS = {"dark": {"page": "#16181d", "side": "#1a1d22"},
           "light": {"page": "#f4f2ec", "side": "#ece8de"}}
_SHELL = dict(_SHELLS[_BASE])      # refreshed in place by apply(), like C
# Typography : two voices. IBM Plex Sans is the console voice (labels, prose);
# IBM Plex Mono is the instrument voice (every numeral, the clock, the tape,
# z-values). A designed pairing with machine heritage — not the default stack.
# NOTE: family names stay UNQUOTED (valid CSS) — these strings are injected into
# single-quoted inline style attributes, where nested quotes would break the HTML
FONT_BODY = "IBM Plex Sans, -apple-system, Segoe UI, system-ui, sans-serif"
FONT_MONO = "IBM Plex Mono, Cascadia Code, Consolas, monospace"

def apply():
    """Resolve the active theme and emit the stylesheet.

    Must be called on every script run. A module-level st.markdown() would
    execute only on first import -- Python caches the module, Streamlit does
    not re-import it -- so every rerun after the first would render unstyled,
    and the palette would be stuck on whatever the theme was at import time.
    """
    global _BASE
    _BASE = _theme_base()
    C.clear()
    C.update(_PALETTES[_BASE])
    _SHELL.clear()
    _SHELL.update(_SHELLS[_BASE])
    st.markdown(f"""<style>
  /* No webfont @import: it was the only external network call in the UI, and
     a captive portal or hanging DNS at the venue would stall first paint on a
     render-blocking stylesheet fetch. The stacks below fall back to Segoe UI /
     system-ui, and pick up IBM Plex automatically when it is installed locally
     (install the fonts on the demo machine to keep the exact brand look). */

  html, body, .stApp, .stApp * {{ font-family: {FONT_BODY}; }}
  /* the global font override must NOT touch Streamlit's icon glyphs: they are
     Material Symbols LIGATURES — in any other font they render as literal text
     like "expand_more" and overlap the label */
  .stApp [data-testid="stIconMaterial"],
  .stApp [data-testid="stExpanderToggleIcon"],
  .stApp span[class*="material-symbols"],
  .stApp i[class*="material-icons"] {{
      font-family: "Material Symbols Rounded" !important; }}
  .stApp {{ background-color: {_SHELL['page']}; color: {C['ink']};
            font-size: 15px; letter-spacing: -0.006em; }}
  .stApp p, .stApp li {{ font-size: 0.94rem; line-height: 1.62; }}

  /* heading scale : tighter tracking, decisive weights */
  .stApp h1 {{ font-size: 1.72rem; font-weight: 750; letter-spacing: -0.028em;
               line-height: 1.15; }}
  .stApp h2 {{ font-size: 1.28rem; font-weight: 700; letter-spacing: -0.022em; }}
  .stApp h3 {{ font-size: 1.08rem; font-weight: 650; letter-spacing: -0.016em; }}
  .stApp h4 {{ font-size: 1.0rem;  font-weight: 650; letter-spacing: -0.012em; }}

  /* code and SQL in a real mono face, slightly smaller than body */
  .stApp code, .stApp pre, .stApp kbd {{ font-family: {FONT_MONO};
               font-size: 0.82em; letter-spacing: 0; }}

  /* captions : smaller, calmer */
  [data-testid="stCaptionContainer"] {{ font-size: 0.8rem !important;
               line-height: 1.5 !important; letter-spacing: -0.003em; }}

  /* widget labels and buttons */
  .stApp label {{ font-size: 0.84rem; font-weight: 500; }}
  .stApp button p {{ font-weight: 600; letter-spacing: -0.006em; }}

  /* metric widgets : numerals are the instrument voice */
  [data-testid="stMetricValue"] {{ font-family: {FONT_MONO}; font-weight: 500;
               letter-spacing: 0; font-variant-numeric: tabular-nums; }}

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
  /* tab labels : sentence case, weight carries the hierarchy */
  .stTabs button[data-baseweb="tab"] p {{
      font-size: 0.94rem; font-weight: 600; letter-spacing: 0; }}
  /* selectbox dropdown renders in a body-level portal, outside .stApp : theme it too */
  div[data-baseweb="popover"] ul[data-baseweb="menu"] {{
      background-color: {_SHELL['side']} !important; border: 1px solid {C['border']}; }}
  div[data-baseweb="popover"] ul[data-baseweb="menu"] li[role="option"] {{
      color: {C['ink']} !important; background-color: transparent; }}
  div[data-baseweb="popover"] ul[data-baseweb="menu"] li[role="option"]:hover,
  div[data-baseweb="popover"] ul[data-baseweb="menu"] li[aria-selected="true"] {{
      background-color: {C['band']} !important; }}
</style>""", unsafe_allow_html=True)
