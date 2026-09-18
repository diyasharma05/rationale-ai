"""Portfolio scan: the dashboard's data layer.

A view model, not engine logic -- it fuses the contract, the series, the
anomaly test and multiplicity control into what one screen needs. It lives
outside the view so it can be unit-tested and reused by the API, and outside
the engine because "what the dashboard shows" is not a property of the KPI.

Takes primitives, never a UI context: that keeps it importable from pytest and
from service/api.py, and it puts role_id visibly in the signature, which is the
RBAC-in-every-cache-key rule made structural.
"""
from engine import anomaly, db, policy, screening


def scan(role_id: str, period: str) -> dict:
    """kpi_id -> (cfg, series, anomaly), for every KPI this role may see.

    The same multiplicity control the investigation applies is applied here, so
    the dashboard and the verdict can never disagree about what is flagged.
    """
    out = {}
    for kpi_id, cfg in db.allowed_kpis(role_id).items():
        series = db.kpi_series(kpi_id, role_id)
        an = anomaly.analyze(series, period, cfg["materiality"], cfg.get("min_history", 6))
        an = screening.screen(an, kpi_id, role_id, period)
        out[kpi_id] = (cfg, series, an)
    return out


def triage(role_id: str, period: str):
    """The scan plus its display order: flagged first, worst first."""
    s = scan(role_id, period)
    return s, policy.severity_order(s)
