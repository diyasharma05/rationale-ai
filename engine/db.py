"""Data access layer: DuckDB over the CSV sources, semantic contract, and
role-based security (row filters + account-name masking) enforced here —
never in the UI.
"""
import hashlib
import os
import threading
from functools import lru_cache

import duckdb
import pandas as pd
import yaml

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

# source table -> (csv file, its date column). The date column is cast ONCE at
# load time; every contract query still says CAST(col AS DATE), which is then a
# free no-op instead of a per-row string parse on every execution.
DATE_COLS = {"sales_orders": "order_date", "ops_fulfilment": "ship_date",
             "crm_events": "event_date", "marketing_weekly": "week_start"}

_SOURCES = {
    "sales_orders": "sales_orders.csv",
    "ops_fulfilment": "ops_fulfilment.csv",
    "crm_events": "crm_events.csv",
    "marketing_weekly": "marketing_weekly.csv",
}

_conn = None
_conn_lock = threading.Lock()


def _build():
    """Materialize the CSV sources as typed TABLEs.

    Deliberately tables, not views: a view over read_csv_auto() re-parses the
    whole file on *every* query (~54 ms per call against an 85k-row CSV, with no
    warm-up benefit). One build at startup costs ~200 ms and makes every
    subsequent query a scan of an in-memory table.
    """
    conn = duckdb.connect()
    for table, fname in _SOURCES.items():
        path = os.path.join(DATA, fname).replace("\\", "/")
        col = DATE_COLS[table]
        conn.execute(
            f"CREATE TABLE {table} AS SELECT * REPLACE (CAST({col} AS DATE) AS {col}) "
            f"FROM read_csv_auto('{path}')")
    return conn


def get_conn():
    """The process-wide DuckDB handle. Built once, under a lock: Streamlit runs
    each session's script in its own thread, so an unguarded check-then-set here
    lets two threads both build the tables."""
    global _conn
    if _conn is None:
        with _conn_lock:
            if _conn is None:          # re-check with the lock held
                _conn = _build()
    return _conn


def query(sql: str, params=()) -> pd.DataFrame:
    """Execute on a per-call cursor over the shared database.

    DuckDB's documented pattern for concurrent use: one database, a cursor per
    thread. Sharing the top-level connection across Streamlit session threads
    interleaves result sets. Every read in the codebase should come through here.
    """
    return get_conn().cursor().execute(sql, params).fetchdf()


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
    df = query(sql)
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
    # ORDER BY 1, 2 (not just 1): ordering by date alone leaves same-day rows
    # in whatever order the parallel aggregation produced, so the frame
    # differed run to run. Harmless for the model, which re-sorts, but it
    # made any content hash of this result unstable.
    sql = ("SELECT CAST(order_date AS DATE) AS date, region, SUM(order_value) AS value "
           "FROM sales_orders WHERE 1=1 {where} GROUP BY 1, 2 ORDER BY 1, 2"
           ).format(where=role_where(role_id))
    return query(sql)


def metric_series(metric_sql: str, role_id: str) -> pd.DataFrame:
    return _run(metric_sql.format(where=role_where(role_id)))


def dim_breakdown(kpi_id: str, dim: str, period: str, role_id: str) -> pd.DataFrame:
    """period: 'YYYY-MM' -> queries that month."""
    cfg = load_contract()["kpis"][kpi_id]
    sql = cfg["dim_sql"].format(dim=dim, period=f"{period}-01", where=role_where(role_id))
    return query(sql)


# ---------------- source freshness (reconciliation across systems) ----------------

@lru_cache(maxsize=1)
def source_freshness():
    """Per source system: latest record date + declared refresh cadence."""
    contract = load_contract()
    out = {}
    for view, col in DATE_COLS.items():
        latest = pd.Timestamp(query(f"SELECT MAX({col}) AS m FROM {view}")["m"].iloc[0]).date()
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
    df = query(
        "SELECT DISTINCT account FROM sales_orders WHERE segment='enterprise' AND account <> ''")
    names = []
    for acc in df["account"]:
        parts = str(acc).split("|")
        if len(parts) == 2:
            names.append(parts[1])
    return sorted(set(names), key=len, reverse=True)  # longest first for safe replace


def _code(name: str) -> str:
    return "ACCT-" + hashlib.sha1(name.encode()).hexdigest()[:4].upper()


def mask_text(text, role_id: str) -> str:
    """Replace enterprise account names with stable ACCT- codes for roles that
    are not cleared to see them.

    Coerces its input: callers include DataFrame.map over columns that can
    hold NaN, and under pandas 3 an Arrow-backed .astype(str) still hands the
    original float to map() -- which crashed the Data page for the executive
    role with "argument of type 'float' is not iterable".
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    if not load_roles()[role_id].get("mask_accounts", False):
        return text
    for name in _account_names():
        if name in text:
            text = text.replace(name, _code(name))
    return text
