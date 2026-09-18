"""The object a page is handed.

Five rules keep this from becoming a god-object:

R1  Ctx carries no data and no engine handles. A page that needs numbers asks
    a service; it never gets a DataFrame or a DB connection through here.
R2  Services take primitives, never Ctx -- which keeps them importable from
    pytest and from the API, and puts role_id visibly in every signature.
R3  Components take explicit arguments, never Ctx, so a chart can be built
    outside a Streamlit run.
R4  Only Nav mutates. st.rerun() belongs in the sidebar and here, nowhere else.
R5  Page-local state stays in st.session_state under a page-prefixed key and
    never enters Ctx. Only cross-page state (role, period, nav, the
    investigation store) lives here.
"""
from dataclasses import dataclass
from typing import Mapping

import pandas as pd
import streamlit as st


@dataclass(frozen=True, slots=True)
class Viewer:
    """Who is looking. Security-relevant, so it is explicit rather than
    reconstructed from session state at each use site."""
    role_id: str
    label: str
    persona: str
    regions: object          # list[str] | "all"
    mask_accounts: bool

    @property
    def is_exec(self) -> bool:
        return self.persona == "executive"

    @property
    def region_label(self) -> str:
        return "all regions" if self.regions == "all" else ", ".join(self.regions)


@dataclass(frozen=True, slots=True)
class Window:
    """Which month is being analysed."""
    period: str
    options: tuple
    default: str

    @property
    def label(self) -> str:
        return pd.Period(self.period, freq="M").strftime("%B %Y")

    @property
    def is_latest(self) -> bool:
        return self.period == self.default


class Nav:
    """The only mutable surface. Deep links go through here so the three
    copies of 'set kpi, set autorun, set nav target, rerun' collapse to one."""

    def goto(self, page: str):
        st.session_state["_nav_target"] = page
        st.rerun()

    def refresh(self):
        """Re-render the current page after a write.

        Not navigation, but the same kind of thing: control flow. Pages that
        mutate state (approving a message, discarding one) need the list they
        just changed to redraw, and routing it through here keeps st.rerun()
        in one place instead of spreading back through the page bodies.
        """
        st.rerun()

    def investigate(self, kpi_id: str, period: str = None):
        st.session_state["kpi_sel"] = kpi_id
        st.session_state["_autorun"] = True
        if period:
            st.session_state["period"] = period
        st.session_state["_nav_target"] = "Investigation"
        st.rerun()


@dataclass(frozen=True, slots=True)
class Ctx:
    viewer: Viewer
    window: Window
    llm: object
    nav: Nav
    store: Mapping          # st.session_state.investigations
