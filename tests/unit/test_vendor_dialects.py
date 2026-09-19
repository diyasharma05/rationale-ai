"""Snowflake and Databricks through the generic seam: everything short of the
network hop is verified here. The drivers register, the URL shapes parse, the
dialect rewrites are exact, and the loader/verifier tool runs end to end
against PostgreSQL as the stand-in server (RATIONALE_TEST_PG). The vendor run
itself needs an account and is documented, not claimed."""
import importlib.util
import os

import pytest
import sqlalchemy

from engine import db

PG = os.environ.get("RATIONALE_TEST_PG")
HAVE_SNOWFLAKE = importlib.util.find_spec("snowflake.sqlalchemy") is not None
HAVE_DATABRICKS = importlib.util.find_spec("databricks.sqlalchemy") is not None

SNOWFLAKE_URL = "snowflake://USER:PASS@ACCOUNT/DB/SCHEMA?warehouse=WH&role=ROLE"
DATABRICKS_URL = "databricks://token:TOKEN@adb-1.azuredatabricks.net?http_path=/sql/1.0/warehouses/abc&catalog=main&schema=rationale"


@pytest.mark.skipif(not HAVE_SNOWFLAKE, reason="snowflake-sqlalchemy not installed")
def test_snowflake_dialect_registers_and_parses_the_url():
    eng = sqlalchemy.create_engine(SNOWFLAKE_URL)          # no connection is made
    assert eng.dialect.name == "snowflake"
    b = db._make_backend(SNOWFLAKE_URL)
    assert b.name == "sql" and b.dialect == "snowflake"
    assert "PASS" not in b.describe() and "***" in b.describe()


@pytest.mark.skipif(not HAVE_DATABRICKS, reason="databricks-sqlalchemy not installed")
def test_databricks_dialect_registers_and_parses_the_url():
    eng = sqlalchemy.create_engine(DATABRICKS_URL)
    assert eng.dialect.name == "databricks"
    b = db._make_backend(DATABRICKS_URL)
    assert b.name == "sql" and b.dialect == "databricks"
    assert "TOKEN" not in b.describe()


def test_databricks_rewrite_touches_only_the_one_spelling():
    contract = db.load_contract()
    for kpi_id, cfg in contract["kpis"].items():
        for key in ("sql", "dim_sql"):
            out = db.rewrite_for("databricks", cfg[key])
            assert "DOUBLE PRECISION" not in out
            assert out.replace("::DOUBLE", "::DOUBLE PRECISION") == cfg[key], (kpi_id, key)
    # nothing else is rewritten for anyone
    for dialect in ("snowflake", "postgresql", "mssql", "sqlite"):
        assert db.rewrite_for(dialect, contract["kpis"]["revenue"]["sql"]) == contract["kpis"]["revenue"]["sql"]


def test_snowflake_results_are_lowercased_to_the_contracts_aliases():
    assert "snowflake" in db._LOWERCASE_RESULTS and "postgresql" not in db._LOWERCASE_RESULTS


def test_bigquery_is_refused_as_an_engine_with_a_reason():
    with pytest.raises(ValueError, match="BigQuery"):
        db._make_backend("bigquery://project/dataset")


def test_dialect_of_strips_the_driver_suffix():
    assert db.dialect_of("postgresql+psycopg://u@h/d") == "postgresql"
    assert db.dialect_of("mssql+pyodbc://u:p@dsn") == "mssql"
    assert db.dialect_of("snowflake://u:p@a/d/s") == "snowflake"


# ---------------------------------------------------------------- the tool, end to end, on PostgreSQL

pg = pytest.mark.skipif(not PG, reason="set RATIONALE_TEST_PG to run the warehouse tool against a real server")
SCHEMA = "wh_tooltest"


def _url_with_schema(dsn: str) -> str:
    base = dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}options=-csearch_path%3D{SCHEMA}"


@pytest.fixture
def schema():
    import psycopg
    with psycopg.connect(PG, autocommit=True) as c, c.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        cur.execute(f"CREATE SCHEMA {SCHEMA}")
    yield SCHEMA
    with psycopg.connect(PG, autocommit=True) as c, c.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")


@pg
def test_warehouse_tool_smoke_load_verify_against_postgresql(schema):
    from ops import warehouse
    url = _url_with_schema(PG)
    s = warehouse.smoke(url)
    assert s["select_1"] == 1 and s["dialect"] == "postgresql"
    loaded = warehouse.load(url, schema=schema)
    assert {t: v["rows"] for t, v in loaded.items()} == {
        "sales_orders": 85222, "ops_fulfilment": 1950, "crm_events": 1156, "marketing_weekly": 280}
    report = warehouse.verify(url)
    assert report["identical"], report["mismatches"][:2]
    assert report["checked"] == 7 + 7 + 4              # analyst, ceo, sales head
    assert all(p["status"] == "warehouse" for p in report["provenance"])
    assert db.backend_info()["backend"] == "duckdb"      # verify() restores the default engine
