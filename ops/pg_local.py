"""Run Rationale.AI on PostgreSQL without Docker, a service, or admin rights.

PostgreSQL ships as a plain zip of binaries. This script runs it as an ordinary
user process with its data directory inside the repo (data/pg/, gitignored),
loads the four CSV sources into it with COPY, creates the append-only events
table the ledger and outbox use, and provisions two roles:

    rationale_admin   owner; runs this script
    rationale_app     what the app connects as: SELECT everywhere, INSERT on
                      events, and nothing else. Append-only by grant.

Then one environment variable moves the whole engine over:

    RATIONALE_DB=postgresql://rationale_app:rationale@localhost:5433/rationale

Commands (python -m ops.pg_local <command>):

    fetch          download the portable PostgreSQL 16 binaries (~320 MB) to ~/pgsql16
    init           initdb + start + provision roles/tables + load the CSVs
    start / stop   the server
    status
    load           (re)load the four source tables from data/*.csv
    reset-ledger   operator reset of the decision ledger and feedback streams
    env            print the RATIONALE_DB line for your shell

Binaries are found via RATIONALE_PG_BIN, then ~/pgsql16/pgsql/bin, then a
standard install, then PATH.
"""
import argparse
import glob
import os
import pathlib
import shutil
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PORT = int(os.environ.get("RATIONALE_PG_PORT", "5433"))
DB = "rationale"
ADMIN = "rationale_admin"
APP_USER, APP_PASSWORD = "rationale_app", "rationale"
DATA_DIR = ROOT / "data" / "pg"
LOG = DATA_DIR / "server.log"
HOME_BIN = pathlib.Path.home() / "pgsql16" / "pgsql" / "bin"

PG_VERSION = "16.10"
EDB_URL = (f"https://get.enterprisedb.com/postgresql/"
           f"postgresql-{PG_VERSION}-1-windows-x64-binaries.zip")

ADMIN_DSN = f"postgresql://{ADMIN}@localhost:{PORT}/{DB}"
ADMIN_MAINT_DSN = f"postgresql://{ADMIN}@localhost:{PORT}/postgres"
APP_DSN = f"postgresql://{APP_USER}:{APP_PASSWORD}@localhost:{PORT}/{DB}"

# DuckDB's inferred CSV types -> PostgreSQL types. Deriving the schema from the
# same inference the DuckDB backend uses is what keeps the two engines typed
# identically, which is what makes their results comparable to the last digit.
_TYPES = {"VARCHAR": "text", "DATE": "date", "TIMESTAMP": "timestamp",
          "BIGINT": "bigint", "INTEGER": "integer", "SMALLINT": "smallint",
          "DOUBLE": "double precision", "FLOAT": "real", "BOOLEAN": "boolean",
          "HUGEINT": "numeric"}


# ---------------------------------------------------------------- binaries

def find_bin() -> pathlib.Path | None:
    cands = []
    if os.environ.get("RATIONALE_PG_BIN"):
        cands.append(pathlib.Path(os.environ["RATIONALE_PG_BIN"]))
    cands.append(HOME_BIN)
    cands += [pathlib.Path(p) for p in sorted(glob.glob(r"C:\Program Files\PostgreSQL\*\bin"), reverse=True)]
    cands += [pathlib.Path(p) for p in sorted(glob.glob("/usr/lib/postgresql/*/bin"), reverse=True)]
    which = shutil.which("pg_ctl")
    if which:
        cands.append(pathlib.Path(which).parent)
    for c in cands:
        if (c / "pg_ctl").exists() or (c / "pg_ctl.exe").exists():
            return c
    return None


def _exe(name: str) -> str:
    b = find_bin()
    if b is None:
        sys.exit("PostgreSQL binaries not found. Run `python -m ops.pg_local fetch`, or set "
                 "RATIONALE_PG_BIN to a directory containing pg_ctl.")
    return str(b / name)


def _run(*args, check=True, capture=False, detach=False):
    """detach=True is for pg_ctl start: the server it spawns inherits pg_ctl's
    handles, so if pg_ctl shares OUR stdout the calling shell waits on that
    pipe for as long as the server lives. Hand it /dev/null instead (the server
    logs to its own file anyway) and, on Windows, its own process group."""
    kw = {}
    if detach:
        kw.update(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.name == "nt":
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0)
    elif capture:
        kw.update(capture_output=True, text=True, encoding="utf-8", errors="replace")
    else:
        kw.update(text=True, encoding="utf-8", errors="replace")
    return subprocess.run(list(args), check=check, **kw)


def fetch():
    dest = pathlib.Path.home() / "pgsql16"
    dest.mkdir(parents=True, exist_ok=True)
    zpath = dest / EDB_URL.rsplit("/", 1)[1]
    if not zpath.exists():
        import urllib.request
        print(f"downloading {EDB_URL}")
        with urllib.request.urlopen(EDB_URL) as r, open(zpath, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done, step = 0, 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total and done * 10 // total > step:
                    step = done * 10 // total
                    print(f"  {step * 10}%")
    print("unpacking bin/, lib/, share/ (skipping pgAdmin, docs, symbols)")
    with zipfile.ZipFile(zpath) as z:
        for m in z.namelist():
            if m.startswith(("pgsql/bin/", "pgsql/lib/", "pgsql/share/")):
                z.extract(m, dest)
    print("binaries:", dest / "pgsql" / "bin")


# ---------------------------------------------------------------- server

def is_running() -> bool:
    r = _run(_exe("pg_ctl"), "-D", str(DATA_DIR), "status", check=False, capture=True)
    return r.returncode == 0


def start():
    if is_running():
        print(f"already running on port {PORT}")
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _run(_exe("pg_ctl"), "-D", str(DATA_DIR), "-l", str(LOG), "-w", "start", detach=True)
    print(f"started on port {PORT}; log at {LOG}")


def stop():
    if not is_running():
        print("not running")
        return
    _run(_exe("pg_ctl"), "-D", str(DATA_DIR), "-m", "fast", "-w", "stop")
    print("stopped")


def status():
    b = find_bin()
    print("binaries:", b or "not found")
    if b:
        print(_run(str(b / "postgres"), "--version", capture=True).stdout.strip())
    if not (DATA_DIR / "PG_VERSION").exists():
        print("data directory: not initialised (run `init`)")
        return
    print("data directory:", DATA_DIR)
    print("server:", "running" if is_running() else "stopped")
    if is_running():
        import psycopg
        with psycopg.connect(APP_DSN, autocommit=True) as c, c.cursor() as cur:
            for t in ("sales_orders", "ops_fulfilment", "crm_events", "marketing_weekly", "events"):
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                print(f"  {t:<18} {cur.fetchone()[0]:>8,} rows")


def initdb():
    if (DATA_DIR / "PG_VERSION").exists():
        print("data directory already initialised")
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # trust auth on localhost: this is a developer instance on one machine. The
    # app still connects as the INSERT-only role, so the grant story holds; a
    # shared or hosted instance would use scram passwords instead.
    _run(_exe("initdb"), "-D", str(DATA_DIR), "-U", ADMIN, "--auth=trust",
         "-E", "UTF8", "--locale=C")
    with open(DATA_DIR / "postgresql.conf", "a", encoding="utf-8") as f:
        f.write(f"\n# rationale.ai local instance\nport = {PORT}\n"
                "listen_addresses = 'localhost'\nlogging_collector = off\n")
    print("initialised", DATA_DIR)


# ---------------------------------------------------------------- provisioning

def provision_roles(maint_dsn: str = ADMIN_MAINT_DSN):
    import psycopg
    with psycopg.connect(maint_dsn, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_USER,))
        if not cur.fetchone():
            # utility statements take no bind parameters; compose the literal safely
            from psycopg import sql
            cur.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(APP_USER), sql.Literal(APP_PASSWORD)))
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB,))
        if not cur.fetchone():
            cur.execute(f"CREATE DATABASE {DB}")
    print(f"roles: {ADMIN} (owner), {APP_USER} (application)")


def provision_schema(admin_dsn: str = ADMIN_DSN, app_user: str = APP_USER):
    """The events table and the grants. Idempotent. Used by the tests too, so
    the append-only guarantee is asserted against the real grants."""
    import psycopg
    from store import PostgresStore
    PostgresStore(admin_dsn).ensure_schema()
    with psycopg.connect(admin_dsn, autocommit=True) as c, c.cursor() as cur:
        cur.execute(f"GRANT USAGE ON SCHEMA public TO {app_user}")
        cur.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {app_user}")
        cur.execute(f"GRANT INSERT ON events TO {app_user}")
        cur.execute(f"GRANT USAGE, SELECT ON SEQUENCE events_id_seq TO {app_user}")
        cur.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM {app_user}")


def _duckdb_schema(csv_path: pathlib.Path) -> list:
    import duckdb
    rows = duckdb.connect().execute(
        f"DESCRIBE SELECT * FROM read_csv_auto('{csv_path.as_posix()}')").fetchall()
    return [(name, _TYPES.get(str(t).split("(")[0].upper(), "text")) for name, t, *_ in rows]


def load_tables(admin_dsn: str = ADMIN_DSN, app_user: str = APP_USER) -> dict:
    """(Re)load the four sources from data/*.csv. Types come from DuckDB's own
    inference so both engines hold identically typed tables; the date column
    is a DATE, as it is in the DuckDB build."""
    import psycopg
    from engine.db import DATE_COLS, _SOURCES
    counts = {}
    with psycopg.connect(admin_dsn, autocommit=True) as c, c.cursor() as cur:
        for table, fname in _SOURCES.items():
            path = ROOT / "data" / fname
            cols = _duckdb_schema(path)
            cols = [(n, "date" if n == DATE_COLS[table] else t) for n, t in cols]
            ddl = ", ".join(f'"{n}" {t}' for n, t in cols)
            cur.execute(f"DROP TABLE IF EXISTS {table}")
            cur.execute(f"CREATE TABLE {table} ({ddl})")
            with open(path, encoding="utf-8") as f, \
                    cur.copy(f"COPY {table} FROM STDIN WITH (FORMAT csv, HEADER true)") as cp:
                while chunk := f.read(1 << 20):
                    cp.write(chunk)
            cur.execute(f"ANALYZE {table}")
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = cur.fetchone()[0]
        cur.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {app_user}")
    return counts


def reset_ledger(admin_dsn: str = ADMIN_DSN):
    """Operator reset: the application role cannot delete, by design."""
    import feedback
    from store import PostgresStore
    s = PostgresStore(admin_dsn)
    s.reset("decision_ledger", [feedback.SEED_ENTRY])
    s.reset("feedback")
    print("decision ledger reset to its seed; feedback cleared")


def env():
    print("# PowerShell")
    print(f'$env:RATIONALE_DB = "{APP_DSN}"')
    print("# bash")
    print(f'export RATIONALE_DB="{APP_DSN}"')


def init():
    initdb()
    start()
    provision_roles()
    provision_schema()
    counts = load_tables()
    for t, n in counts.items():
        print(f"  loaded {t:<18} {n:>8,} rows")
    import feedback
    from store import PostgresStore
    s = PostgresStore(ADMIN_DSN)
    if not s.exists("decision_ledger"):
        s.append("decision_ledger", feedback.SEED_ENTRY)
    print()
    env()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["fetch", "init", "start", "stop", "status", "load",
                                        "reset-ledger", "env"])
    a = ap.parse_args(argv)
    if a.command == "fetch":
        fetch()
    elif a.command == "init":
        init()
    elif a.command == "start":
        start()
    elif a.command == "stop":
        stop()
    elif a.command == "status":
        status()
    elif a.command == "load":
        for t, n in load_tables().items():
            print(f"  loaded {t:<18} {n:>8,} rows")
    elif a.command == "reset-ledger":
        reset_ledger()
    elif a.command == "env":
        env()


if __name__ == "__main__":
    main()
