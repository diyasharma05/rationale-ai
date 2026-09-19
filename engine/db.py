"""Data access layer: the analytics tables, the semantic contract, and
role-based security (row filters + account-name masking) enforced here —
never in the UI.

Two analytics backends behind one `query()`:

  DuckDB      default. In-process, the four CSV sources materialised as typed
              tables at first use. Zero infrastructure; what the offline demo,
              the tests and CI run on.
  PostgreSQL  when RATIONALE_DB is a postgresql:// DSN. The same contract SQL
              runs unchanged against tables loaded by `python -m ops.pg_local`.
              This is the portability claim made concrete: engine/db.py is the
              only file that knows where the data lives, and swapping the engine
              is a connection change plus the two dialect spellings noted in the
              contract -- not a rewrite.

Everything above this file (the contract, the statistics, the gates, RBAC in the
WHERE clause, masking before the prompt) is identical on both.
"""
import datetime as _dt
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


# ---------------- backends ----------------

class _DuckDB:
    name = "duckdb"

    def __init__(self):
        self._conn = None
        self._lock = threading.Lock()

    @staticmethod
    def _build():
        """Materialize the CSV sources as typed TABLEs.

        Deliberately tables, not views: a view over read_csv_auto() re-parses the
        whole file on *every* query (~54 ms per call against an 85k-row CSV, with
        no warm-up benefit). One build at startup costs ~200 ms and makes every
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

    def conn(self):
        """The process-wide DuckDB handle. Built once, under a lock: Streamlit
        runs each session's script in its own thread, so an unguarded
        check-then-set here lets two threads both build the tables."""
        if self._conn is None:
            with self._lock:
                if self._conn is None:          # re-check with the lock held
                    self._conn = self._build()
        return self._conn

    def query(self, sql: str, params=()) -> pd.DataFrame:
        """Execute on a per-call cursor over the shared database.

        DuckDB's documented pattern for concurrent use: one database, a cursor
        per thread. Sharing the top-level connection across Streamlit session
        threads interleaves result sets.
        """
        return self.conn().cursor().execute(sql, params).fetchdf()

    def describe(self) -> str:
        return "DuckDB, in-process, materialised from data/*.csv"


class _Postgres:
    name = "postgresql"

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._local = threading.local()      # one connection per thread; never shared

    def conn(self):
        import psycopg
        from psycopg.types.numeric import FloatLoader
        c = getattr(self._local, "conn", None)
        if c is None or c.closed:
            c = psycopg.connect(self.dsn, autocommit=True)
            # NUMERIC results (e.g. 1000.0 * count / count) arrive as Decimal by
            # default; the engine does float arithmetic on every value column,
            # and DuckDB hands back float64, so load them as floats for parity.
            c.adapters.register_loader("numeric", FloatLoader)
            self._local.conn = c
        return c

    def query(self, sql: str, params=()) -> pd.DataFrame:
        import psycopg
        if params:
            sql = sql.replace("?", "%s")     # DuckDB placeholder -> psycopg placeholder
        try:
            cur = self.conn().cursor()
            cur.execute(sql, params or None)
        except psycopg.OperationalError:
            self._local.conn = None          # one reconnect, then let it raise
            cur = self.conn().cursor()
            cur.execute(sql, params or None)
        cols = [d.name for d in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=cols)
        # Parity with DuckDB's fetchdf(): DATE columns come back as datetime64,
        # not as Python date objects, so downstream code (and the content hash
        # the ML cache is keyed on) sees the same frame from either engine.
        for c in df.columns:
            if df[c].dtype == object:
                nonnull = df[c].dropna()
                if len(nonnull) and isinstance(nonnull.iloc[0], (_dt.date, _dt.datetime)):
                    # microsecond unit to match DuckDB's fetchdf() exactly, so the
                    # two engines produce byte-identical frames and share one
                    # content-hashed ML cache entry instead of one each
                    df[c] = pd.to_datetime(df[c]).astype("datetime64[us]")
        return df

    def describe(self) -> str:
        from store import redact
        return "PostgreSQL at " + redact(self.dsn)


_BACKEND = None
_BACKEND_LOCK = threading.Lock()


def _make_backend(dsn: str):
    from store import is_postgres_dsn
    return _Postgres(dsn) if is_postgres_dsn(dsn) else _DuckDB()


def backend():
    global _BACKEND
    if _BACKEND is None:
        with _BACKEND_LOCK:
            if _BACKEND is None:
                _BACKEND = _make_backend(os.environ.get("RATIONALE_DB", ""))
    return _BACKEND


def set_backend(dsn: str = ""):
    """Point the engine at another analytics store (tests and tooling). Every
    cache derived from the data is cleared, because they are keyed on role and
    period, not on where the rows came from."""
    global _BACKEND
    _BACKEND = _make_backend(dsn or "")
    clear_caches()


def clear_caches():
    for fn in (source_freshness, source_stats, _account_names,
               _kpi_series, _metric_series, _dim_breakdown, _revenue_daily):
        fn.cache_clear()
    try:                                   # derived caches in sibling modules
        from . import screening, stream
        screening.family_qvalues.cache_clear()
        for fn in (stream._daily_region, stream._daily, stream._recent_events):
            fn.cache_clear()
    except Exception:
        pass


def backend_info() -> dict:
    b = backend()
    return {"backend": b.name, "detail": b.describe()}


def get_conn():
    """The DuckDB handle (DuckDB backend only). Kept for tooling; application
    code reads through query()."""
    return backend().conn()


def query(sql: str, params=()) -> pd.DataFrame:
    """Every read in the codebase comes through here, whichever engine is behind it."""
    return backend().query(sql, params)


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


# Result caches, keyed on role (the RBAC-in-every-cache-key rule; a test
# reflects over every cached callable here and asserts it). The tables are a
# process-lifetime snapshot on either backend -- DuckDB materialises the CSVs at
# start-up, PostgreSQL is loaded by an operator -- so caching a query result
# changes nothing about freshness. What it changes is how often the same
# question is asked: one investigation reads the fulfilment-SLA series three
# times (as a driver, and as the upstream of two other drivers), and a
# portfolio scan plus an investigation read every series twice. On PostgreSQL
# each of those is a ~40 ms full-table aggregate over a network round trip;
# on DuckDB ~12 ms. Callers receive a copy, so nobody can mutate the cache.

@lru_cache(maxsize=512)
def _kpi_series(kpi_id: str, role_id: str) -> pd.DataFrame:
    cfg = load_contract()["kpis"][kpi_id]
    return _run(cfg["sql"].format(where=role_where(role_id)))


def kpi_series(kpi_id: str, role_id: str) -> pd.DataFrame:
    return _kpi_series(kpi_id, role_id).copy()


@lru_cache(maxsize=8)
def _revenue_daily(role_id: str) -> pd.DataFrame:
    # ORDER BY 1, 2 (not just 1): ordering by date alone leaves same-day rows
    # in whatever order the parallel aggregation produced, so the frame
    # differed run to run. Harmless for the model, which re-sorts, but it
    # made any content hash of this result unstable.
    sql = ("SELECT CAST(order_date AS DATE) AS date, region, SUM(order_value) AS value "
           "FROM sales_orders WHERE 1=1 {where} GROUP BY 1, 2 ORDER BY 1, 2"
           ).format(where=role_where(role_id))
    return query(sql)


def revenue_daily(role_id: str) -> pd.DataFrame:
    """Daily-grain revenue by region — the training/scoring set for the
    IsolationForest cross-check."""
    return _revenue_daily(role_id).copy()


@lru_cache(maxsize=512)
def _metric_series(metric_sql: str, role_id: str) -> pd.DataFrame:
    return _run(metric_sql.format(where=role_where(role_id)))


def metric_series(metric_sql: str, role_id: str) -> pd.DataFrame:
    return _metric_series(metric_sql, role_id).copy()


@lru_cache(maxsize=2048)
def _dim_breakdown(kpi_id: str, dim: str, period: str, role_id: str) -> pd.DataFrame:
    cfg = load_contract()["kpis"][kpi_id]
    return query(cfg["dim_sql"].format(dim=dim, period=f"{period}-01", where=role_where(role_id)))


def dim_breakdown(kpi_id: str, dim: str, period: str, role_id: str) -> pd.DataFrame:
    """period: 'YYYY-MM' -> queries that month."""
    return _dim_breakdown(kpi_id, dim, period, role_id).copy()


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


@lru_cache(maxsize=8)
def source_stats(role_id: str):
    """Row count and date span per source table, as THIS ROLE sees them.

    Answers "where is this number coming from" with measured facts rather
    than a diagram. Role-scoped on purpose: a lineage page that reported
    85,222 rows to someone whose every query is filtered to two regions
    would be describing a system they cannot actually see, and it would be
    the one place in the app where the row filter did not apply.
    """
    contract = load_contract()
    where = role_where(role_id)
    out = {}
    for table, col in DATE_COLS.items():
        row = query(f"SELECT COUNT(*) AS n, MIN({col}) AS lo, MAX({col}) AS hi "
                    f"FROM {table} WHERE 1=1{where}").iloc[0]
        meta = contract["sources"].get(table, {})
        out[table] = {
            "system": meta.get("system", table),
            "grain": meta.get("grain", ""),
            "refresh": meta.get("refresh", ""),
            "rows": int(row["n"]),
            "first": str(pd.Timestamp(row["lo"]).date()),
            "last": str(pd.Timestamp(row["hi"]).date()),
        }
    return out


def kpi_lineage(kpi_id: str, role_id: str) -> dict:
    """The full chain behind one KPI: which system, which SQL, which levers."""
    cfg = load_contract()["kpis"][kpi_id]
    return {
        "name": cfg["name"],
        "unit": cfg["unit"],
        "owner": cfg.get("owner"),
        "source": cfg.get("source"),
        "system": load_contract()["sources"].get(cfg.get("source"), {}).get("system", "—"),
        "sql": kpi_sql(kpi_id, role_id),
        "dimensions": cfg.get("dimensions", []),
        "drivers": [d.get("kpi") or d.get("metric") for d in cfg.get("drivers", [])],
        "materiality": cfg.get("materiality", {}),
    }


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
