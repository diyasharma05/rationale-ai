"""Rationale.AI : the Streamlit client.

Bootstrap, sidebar, control bar, router. The pages themselves live in
ui/pages/, the view models in services/, and every number comes from
engine/ -- this file should stay small enough to read in one sitting.

Run:  streamlit run app.py
"""
import os

import streamlit as st

import feedback as fb
import telemetry
from engine import db
from llm.client import LLMClient
from ui import context
from ui import theme as _theme
from ui.common import C, DEFAULT_PERIOD, PERIODS, method_chip, month_name
from ui.pages import PAGES, WINDOWED

try:                       # optional: observability is not required to run
    import metrics
except Exception:
    class metrics:         # type: ignore
        ENABLED = False
        serve = staticmethod(lambda: False)
        record_scan = staticmethod(lambda *a, **k: None)
        record_investigation = staticmethod(lambda *a, **k: None)

st.set_page_config(page_title="Rationale.AI", page_icon="🧭", layout="wide")

# Absolute paths: the working directory differs between local runs and hosted
# deployments, so never rely on it.
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")

if not os.path.exists(os.path.join(DATA_DIR, "sales_orders.csv")):
    try:
        import runpy
        with st.spinner("First run : building the synthetic dataset (~30 s)…"):
            runpy.run_path(os.path.join(DATA_DIR, "generate_data.py"), run_name="__main__")
    except Exception:                      # surface, don't white-screen
        import traceback
        st.error("Could not generate the dataset on first boot.")
        st.code(traceback.format_exc(), language="text")
        st.stop()

# data/state/ is gitignored, so a fresh clone or a hosted deploy starts with no
# ledger at all - which silently changes Level-2 retrieval (the seeded Nov-2025
# precedent drops out of the corpus and the [E#] ranks shift). Seed it at boot
# so every machine reasons over the same corpus.
fb.ensure_state()

# Bookmark where this browser session starts in the process-wide telemetry
# log, so the Under the Hood panel can report this session only.
if "_tel_start" not in st.session_state:
    st.session_state["_tel_start"] = telemetry.mark()

_theme.apply()      # every run: Streamlit re-executes this script, not the module
_BASE = _theme._BASE

# The analysis window. The engine is fully parameterised on period, so
# picking a month recomputes everything live.
PERIOD = st.session_state.get("period", DEFAULT_PERIOD)

# ---------------------------------------------------------------- resources


@st.cache_resource
def start_metrics():
    """Expose /metrics for Prometheus once per process (opt-in via env)."""
    return metrics.serve()


@st.cache_resource
def prewarm():
    """RATIONALE_PREWARM=1: run every cold path once at boot so the first click
    in the room is a cache hit. Matters on a remote engine, where each query
    is a round trip; harmless in-process."""
    if os.environ.get("RATIONALE_PREWARM", "").strip() != "1":
        return False
    from engine import stream as _stream
    from services import scan as _scan
    for r in db.load_roles():
        _scan.scan(r, DEFAULT_PERIOD)
        db.source_stats(r)
        _stream._daily_region(r)
    db.source_provenance()
    return True


@st.cache_resource
def get_llm():
    """One client per process. Mock vs live is decided at construction, so
    changing the key clears this cache rather than mutating the client."""
    return LLMClient()


# ---------------------------------------------------------------- sidebar
if "_nav_target" in st.session_state:
    st.session_state.nav = st.session_state.pop("_nav_target")
if "investigations" not in st.session_state:
    st.session_state.investigations = {}

with st.sidebar:
    st.markdown(
        f"<div style='font-size:2.15rem;font-weight:800;letter-spacing:-0.04em;"
        f"line-height:1.1;padding:4px 0 2px;color:{C['ink']}'>"
        f"Rationale<span style='color:"
        f"{'#b48be0' if _BASE == 'dark' else '#7500c0'}'>.AI</span></div>",
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
            # brand purple carries the action role, stepped per mode
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
    nav = st.radio("View", list(PAGES), key="nav",
                   label_visibility="collapsed")
    st.divider()
    llm = get_llm()
    _metrics_up = start_metrics()
    if os.environ.get("RATIONALE_PREWARM", "").strip() == "1":
        with st.spinner(f"Warming caches on {db.backend_info()['label']}…"):
            prewarm()
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
        try:
            fb.reset_ledger()
        except PermissionError as e:      # append-only PostgreSQL store: operator action
            st.warning(str(e))
        else:
            st.session_state.investigations = {}
            telemetry.reset()
            st.success("Ledger, feedback and cached investigations reset.")

# ---- top control bar (Grafana-style): analysis window, top right ----
if nav in WINDOWED:
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

# ---------------------------------------------------------------- live feed

# ---------------------------------------------------------------- data explorer

# ---------------------------------------------------------------- investigation

# ---------------------------------------------------------------- ledger

# ---------------------------------------------------------------- under the hood


# ---------------------------------------------------------------- router
ctx = context.Ctx(
    viewer=context.Viewer(
        role_id=role_id, label=roles[role_id]["label"], persona=persona,
        regions=roles[role_id]["regions"],
        mask_accounts=roles[role_id]["mask_accounts"]),
    window=context.Window(period=PERIOD, options=PERIODS, default=DEFAULT_PERIOD),
    llm=llm,
    nav=context.Nav(),
    store=st.session_state.investigations,
)

PAGES[nav](ctx)
