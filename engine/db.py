"""Data access layer: DuckDB over the CSV sources, semantic contract, and
role-based security (row filters + account-name masking) enforced here —
never in the UI.
"""
import hashlib
import os
from functools import lru_cache

import duckdb
import pandas as pd
import yaml

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

_VIEWS = {
    "sales_orders": "sales_orders.csv",
    "ops_fulfilment": "ops_fulfilment.csv",
    "crm_events": "crm_events.csv",
    "marketing_weekly": "marketing_weekly.csv",
}

_conn = None


def get_conn():
    global _conn
    if _conn is None:
        _conn = duckdb.connect()
        for view, fname in _VIEWS.items():
            path = os.path.join(DATA, fname).replace("\\", "/")
            _conn.execute(f"CREATE OR REPLACE VIEW {view} AS SELECT * FROM read_csv_auto('{path}')")
    return _conn


@lru_cache(maxsize=1)
def load_contract():
    with open(os.path.join(BASE, "contracts", "kpi_contract.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def load_roles():
    with open(os.path.join(BASE, "roles.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)["roles"]


# ---------------- row-level security ----------------

def role_where(role_id: str) -> str:
    role = load_roles()[role_id]
    regions = role.get("regions", "all")
    if regions == "all":
        return ""
    quoted = ",".join(f"'{r}'" for r in regions)
    return f" AND region IN ({quoted})"


def allowed_kpis(role_id: str):
    contract = load_contract()
    return {k: v for k, v in contract["kpis"].items() if role_id in v.get("access", [])}


# ---------------- series queries ----------------

def _run(sql: str) -> pd.DataFrame:
    df = get_conn().execute(sql).fetchdf()
    if "period" in df.columns:
        df["period"] = pd.to_datetime(df["period"]).dt.strftime("%Y-%m")
        df = df.sort_values("period").reset_index(drop=True)
    return df


def kpi_sql(kpi_id: str, role_id: str) -> str:
    """The exact SQL executed for this KPI and role (RBAC WHERE already injected)."""
    cfg = load_contract()["kpis"][kpi_id]
    return " ".join(cfg["sql"].format(where=role_where(role_id)).split())


def kpi_series(kpi_id: str, role_id: str) -> pd.DataFrame:
    cfg = load_contract()["kpis"][kpi_id]
    sql = cfg["sql"].format(where=role_where(role_id))
    return _run(sql)


def revenue_daily(role_id: str) -> pd.DataFrame:
    """Daily-grain revenue by region — the training/scoring set for the
    IsolationForest cross-check."""
    sql = ("SELECT CAST(order_date AS DATE) AS date, region, SUM(order_value) AS value "
           "FROM sales_orders WHERE 1=1 {where} GROUP BY 1, 2 ORDER BY 1") \
        .format(where=role_where(role_id))
    return get_conn().execute(sql).fetchdf()


def metric_series(metric_sql: str, role_id: str) -> pd.DataFrame:
    return _run(metric_sql.format(where=role_where(role_id)))


def dim_breakdown(kpi_id: str, dim: str, period: str, role_id: str) -> pd.DataFrame:
    """period: 'YYYY-MM' -> queries that month."""
    cfg = load_contract()["kpis"][kpi_id]
    sql = cfg["dim_sql"].format(dim=dim, period=f"{period}-01", where=role_where(role_id))
    return get_conn().execute(sql).fetchdf()


# ---------------- source freshness (reconciliation across systems) ----------------

_DATE_COLS = {"sales_orders": "order_date", "ops_fulfilment": "ship_date",
              "crm_events": "event_date", "marketing_weekly": "week_start"}


@lru_cache(maxsize=1)
def source_freshness():
    """Per source system: latest record date + declared refresh cadence."""
    contract = load_contract()
    out = {}
    for view, col in _DATE_COLS.items():
        latest = get_conn().execute(f"SELECT MAX(CAST({col} AS DATE)) FROM {view}").fetchone()[0]
        meta = contract["sources"].get(view, {})
        out[view] = {"system": meta.get("system", view), "grain": meta.get("grain", ""),
                     "refresh": meta.get("refresh", ""), "as_of": str(latest)}
    return out


def system_for_snippet(snippet: dict) -> str:
    """Best-effort mapping of an evidence document to its source system."""
    f = snippet.get("file", "")
    if snippet.get("kind") == "ledger":
        return "Rationale.AI decision ledger"
    if f.startswith(("ticket_", "crm_note_", "transcript_")):
        return "RelateCRM (CRM + Marketing suite)"
    if f.startswith(("ops_note_", "slack_", "postmortem_")):
        return "LogiTrack (WMS) / internal ops"
    return "internal documents"


# ---------------- column-level security (masking) ----------------

@lru_cache(maxsize=1)
def _account_names():
    df = get_conn().execute(
        "SELECT DISTINCT account FROM sales_orders WHERE segment='enterprise' AND account <> ''"
    ).fetchdf()
    names = []
    for acc in df["account"]:
        parts = str(acc).split("|")
        if len(parts) == 2:
            names.append(parts[1])
    return sorted(set(names), key=len, reverse=True)  # longest first for safe replace


def _code(name: str) -> str:
    return "ACCT-" + hashlib.sha1(name.encode()).hexdigest()[:4].upper()


def mask_text(text: str, role_id: str) -> str:
    if not load_roles()[role_id].get("mask_accounts", False):
        return text
    for name in _account_names():
        if name in text:
            text = text.replace(name, _code(name))
    return text
