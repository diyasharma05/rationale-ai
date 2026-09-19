# Platforms: custom where it reasons, hybrid where it lands

The brief says teams may use Databricks, Snowflake, Microsoft Fabric, Tableau,
Qlik, Looker or another technology, build completely custom, or go hybrid. We
chose **custom for the reasoning and hybrid at the edges**, and this page says
exactly which edges exist, what has been proven against what, and what has not.

## Why custom in the middle

The thesis is that the model never computes a number and never chooses a
recipient, and that every number is reproducible from a governed contract. That
is easier to guarantee, test and demonstrate in a small engine we control than
inside a platform's notebook or semantic layer, and it has to run on a laptop
with no network. The engine is about 2,600 lines of Python behind a FastAPI
service; it has no opinion about where the data lives or where the results go.

## The four seams, and their status

| Seam | Mechanism | Proven against | Documented, not run |
|---|---|---|---|
| **Where the data comes from** | The contract's `sources:` block declares a `kind` and a `location` per system. `postgres` and `sql` are fetched live at start-up and fall back to an extract, visibly | `postgres` against a real PostgreSQL; `sql` (any SQLAlchemy URL) against PostgreSQL and SQLite; `csv`, `jsonl`, `parquet` files | `sql` with a Snowflake, Databricks SQL, Fabric or BigQuery URL |
| **Where the contract SQL runs** | `RATIONALE_DB`: unset for in-process DuckDB; a `postgresql://` DSN for the native PostgreSQL backend; any other SQLAlchemy URL for a warehouse | DuckDB and PostgreSQL, with a parity suite asserting identical series and verdicts; the generic SQLAlchemy path against PostgreSQL | Snowflake and Databricks SQL, both of which accept the contract's `date_trunc` and `::DOUBLE PRECISION` as written; BigQuery would need the casts rewritten |
| **Where the ledger and outbox live** | `store.py`: JSONL by default, one PostgreSQL `events` table with an INSERT-only role when configured | Both | Any other transactional store |
| **Where the results land** | `python -m ops.export_bi` writes the scan, the KPI series, the verdicts, the provenance, the contract graph and the evaluation cases as CSV and Parquet; the API serves the same as JSON | Files read back and checked against the live scan in tests | Opening them in Tableau, Power BI, Looker or Qlik |

## The vendor URLs, for the record

| Platform | Driver package | URL shape |
|---|---|---|
| Snowflake | `snowflake-sqlalchemy` | `snowflake://USER:PASS@ACCOUNT/DB/SCHEMA?warehouse=WH&role=ROLE` |
| Databricks SQL | `databricks-sqlalchemy` | `databricks://token:TOKEN@HOST?http_path=/sql/1.0/warehouses/ID&catalog=CAT&schema=SCH` |
| Microsoft Fabric / SQL endpoint | `pyodbc` (ODBC Driver 18) | `mssql+pyodbc://USER:PASS@SERVER/DB?driver=ODBC+Driver+18+for+SQL+Server` |
| BigQuery | `sqlalchemy-bigquery` | `bigquery://PROJECT/DATASET` |
| PostgreSQL (generic path) | `psycopg` | `postgresql+psycopg://USER:PASS@HOST:5432/DB` |

Set the URL in the shell, never in a file that is committed:

```
$env:RATIONALE_OMS_DSN = "<url>"     # fetch the order system live from that warehouse (DuckDB engine)
$env:RATIONALE_DB      = "<url>"     # or run the whole contract there
```

## Snowflake and Databricks: the integration, and its status

Everything short of the network hop is built and verified on this machine:

| Step | Snowflake | Databricks SQL | Verified how |
|---|---|---|---|
| Driver installed | `snowflake-sqlalchemy` 1.11 (connector 4.7) | `databricks-sqlalchemy` 2 (connector 4.5) | `requirements-warehouse.txt`; both import on Python 3.13 |
| Dialect registers, URL parses | yes | yes | `tests/unit/test_vendor_dialects.py` builds an engine from each URL shape without connecting |
| Contract SQL dialect | Accepted as written; unquoted result names come back upper-case, so the engine lower-cases them | Accepted with one spelling swapped: `::DOUBLE PRECISION` becomes `::DOUBLE`, and nothing else | Rewrite rule tested against every KPI's SQL |
| Loader | `write_pandas` (PUT + COPY INTO, seconds for 85k rows), unquoted upper-case identifiers so the contract's unquoted SQL resolves | `pandas.to_sql` in chunks, a one-off of a few minutes | The generic loader is run end to end against PostgreSQL in the test suite |
| Verifier | `python -m ops.warehouse verify --url …` compares every KPI series for every role with DuckDB to 1e-9 and restores the default engine | same | Run end to end against PostgreSQL in the test suite: 18 series, identical |
| **The vendor run** | **Verified 2026-09-19** on a trial account (AWS ap-southeast-3, Snowflake 10.33): 85k-row order table loaded in ~9 s; all 18 KPI series identical to DuckDB to 1e-9; golden path TENTATIVE 0.715 with the same rank-1 driver and the same causal estimate; the tracking bug abstains at 0.438 | **pending an account** | `python -m ops.warehouse smoke / load / verify` against the live account |

The three commands, once a trial exists (Snowflake: thirty days, no card; Databricks: free edition):

```
python -m pip install -r requirements-warehouse.txt
$env:RATIONALE_WAREHOUSE_URL = "snowflake://USER:PASS@ACCOUNT/DB/SCHEMA?warehouse=WH"   # or the databricks:// URL
python -m ops.warehouse smoke      # connect, SELECT 1, name the dialect
python -m ops.warehouse load       # create and load the four tables from the declared sources
python -m ops.warehouse verify     # every KPI series on the warehouse == DuckDB, or the mismatches
python -m ops.warehouse env        # the RATIONALE_OMS_DSN / RATIONALE_DB lines for the app
```

Set the URL in `.env` (gitignored) or the shell, never in a file that is committed.
The tool validates the URL's shape before any library sees it and scrubs the
credential from every message it prints.

### What the Snowflake run taught us

Two things, both now in the code, neither visible without the account:

1. **Snowflake's bulk loader drops date types unless told otherwise.** The
   connector's `write_pandas` writes datetime columns as NUMBER (epoch
   nanoseconds) by default, and `CAST(order_date AS DATE)` then cannot compile.
   `use_logical_type=True` keeps them as TIMESTAMP_NTZ, which the contract casts
   to DATE exactly as on every other engine.
2. **Snowflake divides fixed-point NUMBER values at a limited scale.** The
   complaint-rate ratio came back as 10.817132 where DuckDB and PostgreSQL
   compute 10.81713199824587: identical to four decimals, different at the
   seventh significant digit, and enough to fail a parity check at 1e-9. The
   contract now states the ratio is double arithmetic
   (`COALESCE(c.n,0)::DOUBLE PRECISION`), which every engine honours; after that
   change all 18 series are identical.

### Latency on a remote engine, measured

From this laptop to the Jakarta region, one Snowflake query costs about 0.3 s
after the connection is up (0.43 s before the per-query connection ping was
removed); the first query of a process pays 3 to 4 s to open the connection.
Every page that touches data therefore costs "number of uncached queries times
0.3 s". Three paths were still uncached and have been fixed: the Lineage page's
provenance call (four queries on every render), the role-scoped source
statistics (which called it once per table on first load, nine seconds), and
the Data page's two queries (every widget touch). After the fix:

| Call | First time | Every time after |
|---|---|---|
| Portfolio scan for a role | ~3 s | 16 ms |
| Provenance (Lineage page) | 1.2 s | 0 |
| Source statistics for a role | 1.2 s | 0 |
| Data page query | 0.3 s | 0 |
| Live Feed's daily frame for a role | 1.6 s | 0 |
| First investigation of a KPI | ~20 s | 0.2 s |
| Pre-warming every cold path for all three roles | 12 s, once at boot | — |

`RATIONALE_PREWARM=1` runs that pre-warm when the app starts, behind a spinner,
so the first click in the room is a cache hit. It is harmless on the in-process
engine and worth the twelve seconds on a remote one. The shape is the same as
PostgreSQL (D28), stretched by geography: the role-keyed caches, not the
engine, decide the demo's latency.

## What "proven" means here

`tests/unit/test_warehouse_kind.py` loads a source through the `sql` kind from
SQLite and from PostgreSQL, shows an unreachable warehouse falling back to its
extract with the reason stated and the password redacted, and runs the contract
SQL against PostgreSQL through the generic SQLAlchemy backend with the same
series to a relative tolerance of 1e-9 as the in-process engine.
`tests/integration/test_export_bi.py` checks the export against the live scan.
Snowflake has been run for real on a trial account (see above). Databricks has
not: its free edition would make that claim in an afternoon, and the two
Snowflake findings suggest what to look for (loader type mapping; decimal
arithmetic in ratios).

## The BI tools

The engine is not a dashboard and does not try to be one. Its outputs are
tables and JSON, which is what a dashboard tool wants:

* **Tableau**: text or Parquet connector on the export folder; join `scan` to
  `kpi_series` on `kpi`.
* **Power BI**: Text/CSV or Parquet for the files; or *Get Data → Web* against
  `GET /scan` and `POST /investigate` for live numbers.
* **Looker / Looker Studio**: load the files into the warehouse the engine
  already reads and model them, or a custom connector on the API.
* **Qlik**: file load or the REST connector on `/scan` and `/sources`.
* **Grafana**: already integrated for the engine's operational metrics via
  Prometheus (`compose.yml`).

The number in the dashboard is the number the engine computed; the export is a
copy, not a second computation.
