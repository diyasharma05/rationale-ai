"""The generic warehouse seam: a `sql` source kind and a SQLAlchemy engine backend.

Proven here against SQLite (any machine) and PostgreSQL (when RATIONALE_TEST_PG
is set, always in CI). Snowflake, Databricks, Fabric and BigQuery use the same
two mechanisms with their own driver and URL; that is documented, not tested.
"""
import os

import duckdb
import numpy as np
import pandas as pd
import pytest

from engine import db, explore, sources

BASE = db.BASE
PG = os.environ.get("RATIONALE_TEST_PG")


def _sqlite_with_ops(tmp_path) -> str:
    import sqlalchemy
    url = f"sqlite:///{(tmp_path / 'wms.db').as_posix()}"
    df = pd.read_csv(BASE + "/data/ops_fulfilment.csv")
    eng = sqlalchemy.create_engine(url)
    df.to_sql("ops_fulfilment", eng, index=False)
    eng.dispose()
    return url


def _spec(url, fallback="data/ops_fulfilment.csv"):
    return {"system": "LogiTrack (WMS)", "kind": "sql", "location": url, "table": "ops_fulfilment",
            "fallback": fallback, "grain": "daily x region", "refresh": "daily"}


def test_sql_kind_fetches_live_from_any_sqlalchemy_url(tmp_path):
    url = _sqlite_with_ops(tmp_path)
    conn = duckdb.connect()
    prov = sources.load_one(conn, "ops_fulfilment", _spec(url), "ship_date", BASE)
    assert prov["status"] == "live" and prov["kind"] == "sql"
    assert prov["rows"] == 1950 and prov["fetched_at"]
    assert conn.execute("SELECT typeof(ship_date) FROM ops_fulfilment LIMIT 1").fetchone()[0] == "DATE"


def test_sql_kind_falls_back_visibly_when_the_warehouse_is_unreachable():
    conn = duckdb.connect()
    prov = sources.load_one(conn, "ops_fulfilment",
                            _spec("postgresql+psycopg://nobody:x@127.0.0.1:1/nowhere"), "ship_date", BASE)
    assert prov["status"] == "extract" and "unavailable" in prov["note"]
    assert prov["rows"] == 1950 and ":x@" not in prov["location"]


def test_a_live_kind_needs_a_fallback_extract():
    contract = {"sources": {"t": {"kind": "sql", "location": "sqlite:///x.db"}}, "kpis": {}}
    with pytest.raises(ValueError, match="fallback"):
        sources.registry(contract, BASE)


def test_env_location_unset_means_extract_not_error(monkeypatch):
    monkeypatch.delenv("RATIONALE_WAREHOUSE_URL", raising=False)
    conn = duckdb.connect()
    prov = sources.load_one(conn, "ops_fulfilment", _spec("env:RATIONALE_WAREHOUSE_URL"), "ship_date", BASE)
    assert prov["status"] == "extract" and "not configured" in prov["note"]


def test_backend_selection_by_url_shape():
    assert db._make_backend("").name == "duckdb"
    assert db._make_backend("postgresql://u@h/d").name == "postgresql"
    for url in ("postgresql+psycopg://u@h/d", "snowflake://u:s3cretpw@acct/db/schema",
                "databricks://token:s3cretpw@host?http_path=/sql/1.0", "mssql+pyodbc://u:s3cretpw@dsn"):
        b = db._make_backend(url)
        assert b.name == "sql"
        creds = url.split("://", 1)[1].split("@")[0]
        if ":" in creds:
            assert "***" in b.describe() and creds.split(":", 1)[1] not in b.describe()


# ---------------------------------------------------------------- PostgreSQL through the generic path

pg = pytest.mark.skipif(not PG, reason="set RATIONALE_TEST_PG to prove the generic path against a real server")


def _sa_url(dsn: str) -> str:
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


@pg
def test_sql_kind_against_postgresql_through_sqlalchemy():
    conn = duckdb.connect()
    spec = {**_spec(_sa_url(PG)), "table": "ops_fulfilment"}
    prov = sources.load_one(conn, "ops_fulfilment", spec, "ship_date", BASE)
    assert prov["status"] == "live" and prov["rows"] == 1950


@pg
def test_contract_sql_runs_on_a_warehouse_through_sqlalchemy():
    """The engine backend as any SQLAlchemy URL: same series, same verdict inputs."""
    try:
        db.set_backend(_sa_url(PG))
        assert db.backend_info()["backend"] == "sql"
        b = db.kpi_series("revenue", "analyst")
        _sql, vol = explore.volume("sales_orders", "month", "analyst", "2026-07-01", "2026-07-31")
        assert len(vol) == 1 and int(vol["rows_"].iloc[0]) > 0          # bound params translate
        prov = {p["table"]: p for p in db.source_provenance()}
        assert prov["sales_orders"]["status"] == "warehouse"
    finally:
        db.set_backend("")
    a = db.kpi_series("revenue", "analyst")
    assert list(a["period"]) == list(b["period"])
    np.testing.assert_allclose(a["value"].astype(float), b["value"].astype(float), rtol=1e-9)
