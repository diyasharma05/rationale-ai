"""Append-only event streams: the decision ledger, feedback, the outbox and the
dispatch log.

Every piece of state the engine writes is an event appended to a stream, and
every reader folds a stream back into the view it needs. That was already true
of the four JSONL files under data/state/; this module gives them one interface
and a second place to live.

Two backends, selected by one environment variable:

  JSONL       default. One file per stream under RATIONALE_STATE (data/state/),
              byte-for-byte the files the app has always written. Zero
              infrastructure, which is what an offline demo on a laptop needs.
  PostgreSQL  when RATIONALE_DB is a postgresql:// DSN. One `events` table
              (stream, ts, event jsonb). This is the piece of state that must be
              SHARED for the service to scale horizontally: three API replicas
              writing three ledgers would keep three audit trails and three
              learning loops. In production the application role is granted
              INSERT and SELECT only, so append-only is a grant, not a
              convention -- reset is an operator action.

The analytics tables are switched by the same variable in engine/db.py, so
"run it on Postgres" is one setting, not two.
"""
import json
import os
import pathlib
import threading

BASE = pathlib.Path(__file__).resolve().parent
STREAMS = ("decision_ledger", "feedback", "outbox", "dispatched")


def _jsonable(event: dict) -> dict:
    """Same coercion the JSONL writer has always applied (default=str), so a
    datetime or a Decimal lands identically in either backend."""
    return json.loads(json.dumps(event, default=str))


class JsonlStore:
    name = "jsonl"

    def __init__(self, root):
        self.root = pathlib.Path(root)

    def path(self, stream: str) -> pathlib.Path:
        return self.root / f"{stream}.jsonl"

    def append(self, stream: str, event: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.path(stream), "a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")

    def read(self, stream: str) -> list:
        """Tolerant of a torn line: an interrupted append must not permanently
        break every reader, since the ledger is also the retrieval corpus."""
        p = self.path(stream)
        if not p.exists():
            return []
        out = []
        with open(p, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def exists(self, stream: str) -> bool:
        return self.path(stream).exists()

    def reset(self, stream: str, events=()) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        p = self.path(stream)
        if events:
            with open(p, "w", encoding="utf-8") as f:
                for e in events:
                    f.write(json.dumps(e, default=str) + "\n")
        elif p.exists():
            p.unlink()

    def describe(self) -> str:
        return f"JSONL files in {self.root}"


class PostgresStore:
    name = "postgresql"

    DDL = """
    CREATE TABLE IF NOT EXISTS events (
        id     bigserial PRIMARY KEY,
        stream text        NOT NULL,
        ts     timestamptz NOT NULL DEFAULT now(),
        event  jsonb       NOT NULL
    );
    CREATE INDEX IF NOT EXISTS events_stream_id ON events (stream, id);
    """

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._local = threading.local()      # psycopg connections are not shared across threads

    def _conn(self):
        import psycopg
        c = getattr(self._local, "conn", None)
        if c is None or c.closed:
            c = psycopg.connect(self.dsn, autocommit=True)
            self._local.conn = c
        return c

    def ensure_schema(self) -> None:
        """Operator action: needs CREATE on the schema. The application role
        does not have it, and does not need it."""
        with self._conn().cursor() as cur:
            cur.execute(self.DDL)

    def append(self, stream: str, event: dict) -> None:
        from psycopg.types.json import Jsonb
        with self._conn().cursor() as cur:
            cur.execute("INSERT INTO events (stream, event) VALUES (%s, %s)",
                        (stream, Jsonb(_jsonable(event))))

    def read(self, stream: str) -> list:
        with self._conn().cursor() as cur:
            cur.execute("SELECT event FROM events WHERE stream = %s ORDER BY id", (stream,))
            return [row[0] for row in cur.fetchall()]

    def exists(self, stream: str) -> bool:
        with self._conn().cursor() as cur:
            cur.execute("SELECT EXISTS (SELECT 1 FROM events WHERE stream = %s)", (stream,))
            return bool(cur.fetchone()[0])

    def reset(self, stream: str, events=()) -> None:
        """Delete only when there is something to delete, so seeding an empty
        stream works for the INSERT-only application role; a real reset of a
        populated stream needs the operator role and says so."""
        import psycopg
        if self.exists(stream):
            try:
                with self._conn().cursor() as cur:
                    cur.execute("DELETE FROM events WHERE stream = %s", (stream,))
            except psycopg.errors.InsufficientPrivilege as e:
                raise PermissionError(
                    "append-only store: this role may not delete events. Resetting a "
                    "populated stream is an operator action: python -m ops.pg_local "
                    "reset-ledger") from e
        for e in events:
            self.append(stream, e)

    def describe(self) -> str:
        return "PostgreSQL events table at " + redact(self.dsn)


def redact(dsn: str) -> str:
    """postgresql://user:secret@host/db -> postgresql://user:***@host/db"""
    if "@" in dsn and "://" in dsn:
        head, tail = dsn.split("://", 1)
        creds, rest = tail.rsplit("@", 1)
        user = creds.split(":", 1)[0]
        return f"{head}://{user}:***@{rest}" if ":" in creds else f"{head}://{creds}@{rest}"
    return dsn


def is_postgres_dsn(value: str) -> bool:
    return str(value or "").strip().startswith(("postgresql://", "postgres://"))


_store = None
_lock = threading.Lock()


def _make():
    """RATIONALE_DB moves both the analytics tables and the event streams.
    RATIONALE_STORE overrides just the streams: "jsonl" keeps a throwaway
    ledger on disk while the numbers come from PostgreSQL (eval.py and the
    benchmark do this, so a scoring run never writes into a shared ledger),
    and a postgresql:// DSN sends the streams somewhere of their own."""
    override = os.environ.get("RATIONALE_STORE", "").strip()
    dsn = os.environ.get("RATIONALE_DB", "").strip()
    if is_postgres_dsn(override):
        return PostgresStore(override)
    if override.lower() == "jsonl" or not is_postgres_dsn(dsn):
        root = os.environ.get("RATIONALE_STATE") or str(BASE / "data" / "state")
        return JsonlStore(root)
    return PostgresStore(dsn)


def current():
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                _store = _make()
    return _store


def reconfigure(store=None) -> None:
    """Swap the active store (tests and tooling). None re-reads the environment."""
    global _store
    _store = store


def append(stream: str, event: dict) -> None:
    current().append(stream, event)


def read(stream: str) -> list:
    return current().read(stream)


def exists(stream: str) -> bool:
    return current().exists(stream)


def reset(stream: str, events=()) -> None:
    current().reset(stream, events)


def backend_info() -> dict:
    s = current()
    return {"backend": s.name, "detail": s.describe()}
