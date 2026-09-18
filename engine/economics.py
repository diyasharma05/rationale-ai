"""Money and formatting — the single place a rupee figure is produced.

This existed in three places: app.py's monthly_impact, and two inlined copies
inside pyramid.investigate. Three copies of a formula that turns a daily
run-rate into a monthly impact is three chances for the dashboard and the
narrative to quote different numbers for the same movement.
"""

# Days used to annualise a daily run-rate into "per month". A deliberate
# simplification (real months are 28-31 days), kept because the KPI is defined
# as a run-rate precisely so calendar length does not drive the comparison.
IMPACT_DAYS = 30


def fmt_value(v, unit: str) -> str:
    """Human-readable KPI value. Indian numbering for money (lakh / crore)."""
    if v is None:
        return "n/a"
    if unit.startswith("INR"):
        suffix = "/day" if unit.endswith("/day") else ""
        base = f"₹{v/1e7:.2f} Cr" if abs(v) >= 1e7 else f"₹{v/1e5:.2f} L"
        return base + suffix
    if unit == "%":
        return f"{v:.1f}%"
    return f"{v:,.1f} {unit}"


def monthly_impact(an: dict, unit: str):
    """Rupee impact per month of a movement away from baseline.

    Only defined for daily run-rate money KPIs; returns None otherwise so
    callers never have to repeat the unit check.
    """
    if unit != "INR/day":
        return None
    cur, mean = an.get("current"), an.get("mean")
    if cur is None or mean is None:
        return None
    return (cur - mean) * IMPACT_DAYS
