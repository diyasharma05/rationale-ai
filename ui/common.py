"""Shared view helpers, re-exported in one place.

Pages import from here rather than from six modules each. This is a
convenience layer, not a dumping ground: everything below is either a pure
formatter or a re-export of something that already has a proper home.
"""
import pandas as pd

from engine import economics, policy
from llm import fallback
from ui.components.actions import render_actions          # noqa: F401
from ui.components.charts import (base_layout,            # noqa: F401
                                  confidence_components, confidence_gauge,
                                  contribution_waterfall, delta_bar,
                                  gate_bullets, hypothesis_bars, sparkline)
from ui.components.method import (METHODS, method_chip,   # noqa: F401
                                  method_chip_row, method_strip)
from ui.components.tiles import (badge, pill,             # noqa: F401
                                 section_label, stat_tile)
from ui.theme import C, FONT_BODY, FONT_MONO              # noqa: F401

# The analysis window the demo ships with. 2026-08 exists in the data but is
# deliberately not offered: the incident and every recorded fixture are pinned
# to July, so an extra month would be a path with no narrative behind it.
PERIODS = ("2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07")
DEFAULT_PERIOD = "2026-07"

fmt = economics.fmt_value
monthly_impact = economics.monthly_impact
human_line = fallback.kpi_one_liner
severity_order = policy.severity_order
lever_approval = policy.lever_approval


def month_name(period: str) -> str:
    return pd.Period(period, freq="M").strftime("%B %Y")
