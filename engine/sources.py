"""Heterogeneous sources, reconciled at ingestion.

The brief asks the engine to reconcile data and business context across
heterogeneous sources. The semantic contract declares each source's system,
grain and refresh cadence; this module is where those declarations meet real
formats and real connections:

    kind: postgres   a live transactional database (the OMS). Fetched at
                     start-up over the wire; if it is unreachable or not
                     configured, the last extract is used and the provenance
                     says so. Nothing is silently substituted.
    kind: csv        a flat-file extract dropped by a system on a schedule
                     (the WMS daily file, the marketing weekly file).
    kind: jsonl      an event export, one JSON object per line (the CRM feed).
    kind: parquet    a lakehouse file, for completeness.

Every source lands in one governed namespace as a typed table with its date
column cast once, so the contract SQL joins across systems (complaint rate is
CRM events over OMS orders) without knowing or caring where each side came
from. What it does know is recorded: `provenance()` reports, per source, the
system, the kind, the (redacted) location, whether it was live or an extract,
the row count, the latest record date and when it was fetched. The Lineage
page and the API show that record; the reconciliation is visible, not
asserted.
"""
import datetime as _dt
import os
import pathlib
import tempfile
import time

from store import redact

KINDS = ("csv", "jsonl", "json", "parquet", "postgres")
LIVE_TIMEOUT_S = 3


def registry(contract: dict, base: str) -> dict:
    """table -> normalised source spec from the contract's `sources` block.

    Defaults keep older contracts working: a source with no `kind` is a CSV
    named after the table under data/.
    """
    out = {}
    for table, spec in (contract.get("sources") or {}).items():
        s = dict(spec)
        s.setdefault("kind", "csv")
        s.setdefault("location", f"data/{table}.csv")
        s.setdefault("table", table)
        if s["kind"] not in KINDS:
            raise ValueError(f"source {table}: unknown kind {s['kind']!r}")
        if s["kind"] == "postgres" and not s.get("fallback"):
            raise ValueError(f"source {table}: a postgres source needs a `fallback` extract")
        out[table] = s
    return out


def resolve_location(location: str, base: str) -> str:
    """'env:NAME' reads an environment variable (empty if unset); relative
    paths are relative to the repository root."""
    if location.startswith("env:"):
        return os.environ.get(location[4:], "").strip()
    p = pathlib.Path(location)
    return str(p if p.is_absolute() else pathlib.Path(base) / p)


def _reader(kind: str, path: str) -> str:
    path = path.replace("\\", "/")
    if kind == "csv":
        return f"read_csv_auto('{path}')"
    if kind in ("jsonl", "json"):
        return f"read_json_auto('{path}')"
    if kind == "parquet":
        return f"read_parquet('{path}')"
    raise ValueError(kind)


def _create(conn, table: str, kind: str, path: str, date_col: str) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute(
        f"CREATE TABLE {table} AS SELECT * REPLACE (CAST({date_col} AS DATE) AS {date_col}) "
        f"FROM {_reader(kind, path)}")


def _fetch_postgres(dsn: str, table: str) -> str:
    """Pull a table from a live PostgreSQL over the wire into a temporary CSV
    (COPY TO STDOUT, the fastest path out of PostgreSQL) and return its path."""
    import psycopg
    fd, tmp = tempfile.mkstemp(prefix=f"rationale_{table}_", suffix=".csv")
    os.close(fd)
    with psycopg.connect(dsn, connect_timeout=LIVE_TIMEOUT_S) as c, c.cursor() as cur, \
            open(tmp, "w", encoding="utf-8", newline="") as f:
        with cur.copy(f"COPY (SELECT * FROM {table}) TO STDOUT WITH (FORMAT csv, HEADER true)") as cp:
            for chunk in cp:
                f.write(bytes(chunk).decode("utf-8"))
    return tmp


def load_one(conn, table: str, spec: dict, date_col: str, base: str, allow_live: bool = True) -> dict:
    """Load one source into the engine's namespace; return its provenance."""
    kind = spec["kind"]
    prov = {"table": table, "system": spec.get("system", table), "kind": kind,
            "grain": spec.get("grain", ""), "refresh": spec.get("refresh", ""),
            "location": "", "status": "", "note": "", "fetched_at": None}
    t0 = time.perf_counter()
    if kind == "postgres":
        dsn = resolve_location(spec["location"], base) if allow_live else ""
        prov["location"] = redact(dsn) if dsn else spec["location"]
        fallback = resolve_location(spec["fallback"], base)
        if not dsn:
            prov.update(status="extract", note="source not configured; using the last extract",
                        location=f"{spec['location']} (unset) -> {spec['fallback']}")
            _create(conn, table, "csv", fallback, date_col)
        else:
            try:
                tmp = _fetch_postgres(dsn, spec["table"])
                try:
                    _create(conn, table, "csv", tmp, date_col)
                finally:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                prov.update(status="live", fetched_at=_dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                            note=f"fetched over the wire in {(time.perf_counter() - t0) * 1000:.0f} ms")
            except Exception as e:                # unreachable, wrong credentials, missing table ...
                prov.update(status="extract",
                            note=f"live source unavailable ({type(e).__name__}); using the last extract",
                            location=f"{redact(dsn)} -> {spec['fallback']}")
                _create(conn, table, "csv", fallback, date_col)
    else:
        path = resolve_location(spec["location"], base)
        prov.update(location=spec["location"], status="file")
        _create(conn, table, kind, path, date_col)
    row = conn.execute(f"SELECT COUNT(*) AS n, MAX({date_col}) AS m FROM {table}").fetchone()
    prov["rows"] = int(row[0])
    prov["as_of"] = str(row[1])[:10] if row[1] is not None else None
    return prov


def load_all(conn, contract: dict, date_cols: dict, base: str, allow_live: bool = True) -> list:
    return [load_one(conn, table, spec, date_cols[table], base, allow_live)
            for table, spec in registry(contract, base).items()]


def summary(provenance: list) -> dict:
    systems = {p["system"] for p in provenance}
    kinds = {p["kind"] for p in provenance}
    return {"systems": len(systems), "kinds": sorted(kinds),
            "live": sum(1 for p in provenance if p["status"] == "live"),
            "extract": sum(1 for p in provenance if p["status"] == "extract"),
            "file": sum(1 for p in provenance if p["status"] == "file")}
