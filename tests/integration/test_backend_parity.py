"""Same contract, two engines, same verdicts.

The portability claim -- engine/db.py is the one seam, and the semantic
contract runs unchanged on another SQL engine -- is only worth making if it is
measured. This suite loads the CSV sources into a real PostgreSQL (the local
instance from `python -m ops.pg_local init`, or CI's service container), then
runs the SAME functions against DuckDB and PostgreSQL and asserts the numbers
and the verdicts agree.

It also asserts the append-only grant on the application role for real: the
role can INSERT into the events table and cannot UPDATE or DELETE anything.

Opt-in: set RATIONALE_TEST_PG to an owner/superuser DSN.
"""
import os
from contextlib import contextmanager

import numpy as np
import pandas as pd
import pytest

import store
from engine import db, pyramid
from ops import pg_local

PG = os.environ.get("RATIONALE_TEST_PG")
pytestmark = pytest.mark.skipif(not PG, reason="set RATIONALE_TEST_PG to run the PostgreSQL parity suite")

PERIOD = "2026-07"
ROLES = ["analyst", "ceo", "sales_head_north"]
TESTABLE = ["revenue", "fulfilment_sla", "complaint_rate", "enterprise_active_accounts",
            "marketing_conversion", "aov"]


def _app_dsn(admin_dsn: str) -> str:
    """Same server and database as the admin DSN, connected as the application role."""
    tail = admin_dsn.split("@", 1)[1] if "@" in admin_dsn else admin_dsn.split("://", 1)[1]
    return f"postgresql://{pg_local.APP_USER}:{pg_local.APP_PASSWORD}@{tail}"


@contextmanager
def on(dsn: str):
    db.set_backend(dsn)
    try:
        yield
    finally:
        db.set_backend("")


@pytest.fixture(scope="module")
def loaded_pg():
    pg_local.provision_roles(PG)
    pg_local.provision_schema(PG)
    counts = pg_local.load_tables(PG)
    yield counts
    db.set_backend("")


def test_row_counts_match_duckdb(loaded_pg):
    for table, n in loaded_pg.items():
        with on(""):
            d = int(db.query(f"SELECT COUNT(*) AS n FROM {table}")["n"].iloc[0])
        assert d == n, table


def test_every_kpi_series_is_identical_on_both_engines(loaded_pg):
    for role in ROLES:
        for kpi in db.allowed_kpis(role):
            with on(""):
                a = db.kpi_series(kpi, role)
            with on(PG):
                b = db.kpi_series(kpi, role)
            assert list(a["period"]) == list(b["period"]), (kpi, role)
            np.testing.assert_allclose(a["value"].astype(float), b["value"].astype(float),
                                       rtol=1e-9, err_msg=f"{kpi}/{role}")


def test_breakdowns_and_the_daily_frame_match(loaded_pg):
    for dim in ("region", "segment", "category"):
        with on(""):
            a = db.dim_breakdown("revenue", dim, PERIOD, "analyst").sort_values("member").reset_index(drop=True)
        with on(PG):
            b = db.dim_breakdown("revenue", dim, PERIOD, "analyst").sort_values("member").reset_index(drop=True)
        assert list(a["member"]) == list(b["member"]), dim
        np.testing.assert_allclose(a["value"].astype(float), b["value"].astype(float), rtol=1e-9)
    with on(""):
        a = db.revenue_daily("analyst")
    with on(PG):
        b = db.revenue_daily("analyst")
    assert len(a) == len(b)
    assert pd.to_datetime(a["date"]).iloc[[0, -1]].tolist() == pd.to_datetime(b["date"]).iloc[[0, -1]].tolist()
    np.testing.assert_allclose(a["value"].astype(float), b["value"].astype(float), rtol=1e-9)


def test_the_scan_flags_the_same_kpis(loaded_pg):
    from services import scan
    with on(""):
        a = {k for k, (_c, _s, an) in scan.scan("analyst", PERIOD).items() if an["material"]}
    with on(PG):
        b = {k for k, (_c, _s, an) in scan.scan("analyst", PERIOD).items() if an["material"]}
    assert a == b == {"revenue", "fulfilment_sla", "complaint_rate",
                      "enterprise_active_accounts", "marketing_conversion"}


def test_july_verdicts_are_identical(loaded_pg, llm):
    """Outcome, confidence to three decimals, and the rank-1 explanation."""
    def run(dsn):
        out = {}
        with on(dsn):
            for k in TESTABLE:
                r = pyramid.investigate(k, PERIOD, "analyst", llm)
                top = next(((h.get("driver_id") or h["source"]) for h in r["hypotheses"]
                            if h.get("rank") == 1), None)
                out[k] = (r["outcome"], r["confidence"]["value"], top)
        return out
    assert run("") == run(PG)


def test_bound_parameters_translate_for_postgres(loaded_pg):
    """The Data page binds its date slider as parameters. DuckDB spells the
    placeholder '?', psycopg '%s'; the backend translates, the page does not."""
    from engine import explore
    with on(PG):
        _sql, df = explore.volume("sales_orders", "month", "analyst", "2026-07-01", "2026-07-31")
        assert len(df) == 1 and int(df["rows_"].iloc[0]) > 0
        _sql, rows = explore.latest_rows("sales_orders", "sales_head_north",
                                         "2026-07-01", "2026-07-31", limit=5)
        assert 0 < len(rows) <= 5
        assert set(rows["region"]) <= {"North", "North-West"}       # RBAC holds on the second engine


def test_app_role_is_insert_only(loaded_pg):
    """Append-only by grant, not by convention."""
    import psycopg
    app = _app_dsn(PG)
    s = store.PostgresStore(app)
    s.append("test_stream_grants", {"ok": True})
    assert s.read("test_stream_grants")[-1] == {"ok": True}
    with psycopg.connect(app, autocommit=True) as c, c.cursor() as cur:
        for stmt in ("DELETE FROM events WHERE stream = 'test_stream_grants'",
                     "UPDATE events SET event = '{}' WHERE stream = 'test_stream_grants'",
                     "UPDATE sales_orders SET order_value = 0 WHERE false",
                     "DELETE FROM sales_orders WHERE false"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(stmt)
    with pytest.raises(PermissionError):
        s.reset("test_stream_grants")                 # the app cannot clear a populated stream
    store.PostgresStore(PG).reset("test_stream_grants")   # the operator can


def test_engine_and_store_report_postgres_when_configured(loaded_pg, monkeypatch):
    monkeypatch.setenv("RATIONALE_DB", PG)
    store.reconfigure(None)
    try:
        info = store.backend_info()
        assert info["backend"] == "postgresql"
        assert "@" not in PG or ":***@" in info["detail"] or ":" not in PG.split("://", 1)[1].split("@")[0]
    finally:
        monkeypatch.delenv("RATIONALE_DB")
        store.reconfigure(None)
    with on(PG):
        assert db.backend_info()["backend"] == "postgresql"
    assert db.backend_info()["backend"] == "duckdb"
