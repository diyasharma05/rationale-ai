"""Load the governed sources into a warehouse and prove the contract runs there.

The same two seams the engine already has -- any SQLAlchemy URL as a source or
as the engine -- pointed at Snowflake, Databricks SQL, Microsoft Fabric or
PostgreSQL. This tool does the operator's part: create the four tables from the
declared sources (read through engine/sources.py, so the types match what the
in-process engine holds), load them, and then run every KPI series through the
warehouse and compare it with DuckDB to the last digit.

    python -m ops.warehouse smoke  --url "$URL"     # connect, SELECT 1, name the dialect
    python -m ops.warehouse load   --url "$URL"     # create + load the four tables
    python -m ops.warehouse verify --url "$URL"     # contract SQL on the warehouse == DuckDB?
    python -m ops.warehouse env    --url "$URL"     # the two lines to set in your shell

URL shapes (set them in the shell, never in a committed file):

    snowflake://USER:PASS@ACCOUNT/DB/SCHEMA?warehouse=WH&role=ROLE
    databricks://token:TOKEN@HOST?http_path=/sql/1.0/warehouses/ID&catalog=CAT&schema=SCH
    mssql+pyodbc://USER:PASS@SERVER/DB?driver=ODBC+Driver+18+for+SQL+Server
    postgresql+psycopg://USER:PASS@HOST:5432/DB

Snowflake is loaded with the connector's write_pandas (a PUT + COPY INTO under
the hood, seconds for 85k rows); everything else through pandas.to_sql in
chunks, which is minutes for the order table and is a one-off.
"""
import argparse
import os
import sys
import time

import duckdb
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("MOCK_MODE", "1")

from engine import db, sources                              # noqa: E402
from store import redact                                    # noqa: E402

ROLES = ("analyst", "ceo", "sales_head_north")


def frames() -> dict:
    """The four sources as typed frames, exactly as the DuckDB engine ingests them
    (from their extract files; a warehouse load is what the extract is for)."""
    scratch = duckdb.connect()
    sources.load_all(scratch, db.load_contract(), db.DATE_COLS, ROOT, allow_live=False)
    out = {}
    for table, col in db.DATE_COLS.items():
        df = scratch.execute(f"SELECT * FROM {table}").df()
        df[col] = pd.to_datetime(df[col])
        out[table] = df
    return out


def smoke(url: str) -> dict:
    import sqlalchemy
    t0 = time.perf_counter()
    eng = sqlalchemy.create_engine(url)
    try:
        with eng.connect() as c:
            one = c.execute(sqlalchemy.text("SELECT 1 AS one")).scalar()
    finally:
        eng.dispose()
    return {"dialect": db.dialect_of(url), "url": redact(url), "select_1": one,
            "ms": round((time.perf_counter() - t0) * 1000)}


def _load_snowflake(url: str, table: str, df: pd.DataFrame, schema: str | None) -> int:
    import snowflake.connector
    from snowflake.connector.pandas_tools import write_pandas
    from sqlalchemy.engine import make_url
    u = make_url(url)
    database, sch = (u.database or "").split("/", 1) if "/" in (u.database or "") else (u.database, None)
    kw = {"user": u.username, "password": u.password, "account": u.host,
          "database": database, "schema": schema or sch, **{k: v for k, v in u.query.items()}}
    conn = snowflake.connector.connect(**{k: v for k, v in kw.items() if v})
    try:
        # unquoted identifiers: Snowflake upper-cases them, and the contract's
        # unquoted lower-case SQL resolves to the same names
        ok, _chunks, nrows, _ = write_pandas(conn, df, table.upper(), auto_create_table=True,
                                             overwrite=True, quote_identifiers=False)
        assert ok
        return int(nrows)
    finally:
        conn.close()


def _load_generic(url: str, table: str, df: pd.DataFrame, schema: str | None) -> int:
    import sqlalchemy
    eng = sqlalchemy.create_engine(url)
    try:
        df.to_sql(table, eng, schema=schema, if_exists="replace", index=False,
                  method="multi", chunksize=500)
        with eng.connect() as c:
            q = f'SELECT COUNT(*) FROM {schema + "." if schema else ""}{table}'
            return int(c.execute(sqlalchemy.text(q)).scalar())
    finally:
        eng.dispose()


def _load_postgres(url: str, table: str, df: pd.DataFrame, schema: str | None) -> int:
    """PostgreSQL targets: let pandas create the typed table, then COPY the rows
    (seconds, where chunked INSERTs are minutes)."""
    import io
    import psycopg
    import sqlalchemy
    eng = sqlalchemy.create_engine(url)
    try:
        df.head(0).to_sql(table, eng, schema=schema, if_exists="replace", index=False)
    finally:
        eng.dispose()
    dsn = url.replace("postgresql+psycopg://", "postgresql://", 1)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    target = f'{schema + "." if schema else ""}{table}'
    with psycopg.connect(dsn, autocommit=True) as c, c.cursor() as cur:
        with cur.copy(f"COPY {target} FROM STDIN WITH (FORMAT csv, HEADER true)") as cp:
            while chunk := buf.read(1 << 20):
                cp.write(chunk)
        cur.execute(f"SELECT COUNT(*) FROM {target}")
        return int(cur.fetchone()[0])


def load(url: str, schema: str | None = None) -> dict:
    dialect = db.dialect_of(url)
    loader = {"snowflake": _load_snowflake, "postgresql": _load_postgres}.get(dialect, _load_generic)
    out = {}
    for table, df in frames().items():
        t0 = time.perf_counter()
        n = loader(url, table, df, schema)
        out[table] = {"rows": n, "ms": round((time.perf_counter() - t0) * 1000)}
    return out


def verify(url: str, roles=ROLES, rtol: float = 1e-9) -> dict:
    """Every KPI series for every role: the warehouse against DuckDB."""
    report = {"dialect": db.dialect_of(url), "url": redact(url), "checked": 0, "mismatches": []}
    ref = {}
    db.set_backend("")
    for role in roles:
        for kpi in db.allowed_kpis(role):
            ref[(kpi, role)] = db.kpi_series(kpi, role)
    try:
        db.set_backend(url)
        report["engine"] = db.backend_info()["detail"]
        for (kpi, role), a in ref.items():
            b = db.kpi_series(kpi, role)
            report["checked"] += 1
            same = list(a["period"]) == list(b["period"]) and np.allclose(
                a["value"].astype(float), b["value"].astype(float), rtol=rtol, atol=1e-9)
            if not same:
                report["mismatches"].append({"kpi": kpi, "role": role,
                                             "duckdb": a["value"].round(4).tolist(),
                                             "warehouse": b["value"].round(4).tolist()})
        report["provenance"] = [{k: p[k] for k in ("table", "status", "rows")} for p in db.source_provenance()]
    finally:
        db.set_backend("")
    report["identical"] = not report["mismatches"]
    return report


def env(url: str):
    print("# the order system fetched live from this warehouse (DuckDB stays the engine):")
    print(f'$env:RATIONALE_OMS_DSN = "{url}"')
    print("# or the whole contract executed on this warehouse:")
    print(f'$env:RATIONALE_DB = "{url}"')
    print("# (bash: export NAME=\"...\")   set these in the shell, never in a committed file")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["smoke", "load", "verify", "env"])
    ap.add_argument("--url", default=os.environ.get("RATIONALE_WAREHOUSE_URL", ""),
                    help="SQLAlchemy URL (or set RATIONALE_WAREHOUSE_URL)")
    ap.add_argument("--schema", default=None, help="target schema for load (generic loaders)")
    a = ap.parse_args(argv)
    if not a.url:
        sys.exit("give --url or set RATIONALE_WAREHOUSE_URL")
    if a.command == "smoke":
        r = smoke(a.url)
        print(f"{r['dialect']}: SELECT 1 -> {r['select_1']} in {r['ms']} ms at {r['url']}")
    elif a.command == "load":
        for t, info in load(a.url, a.schema).items():
            print(f"  loaded {t:<18} {info['rows']:>8,} rows  {info['ms']:>7} ms")
    elif a.command == "verify":
        r = verify(a.url)
        print(f"{r['dialect']}: {r['checked']} KPI series compared with DuckDB -> "
              f"{'IDENTICAL' if r['identical'] else str(len(r['mismatches'])) + ' MISMATCHES'}")
        for m in r["mismatches"][:5]:
            print("   ", m)
        sys.exit(0 if r["identical"] else 1)
    elif a.command == "env":
        env(a.url)


if __name__ == "__main__":
    main()
