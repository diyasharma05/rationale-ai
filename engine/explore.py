"""Ad-hoc source exploration, with RBAC and an allowlist.

The Data page used to build this SQL itself with f-strings, which meant the
last piece of query construction in the system lived in the view, the date
slider interpolated straight into the statement, and engine/db.py's date-column
map had a second copy in app.py.
"""
from functools import lru_cache

from . import db

GRAINS = ("day", "week", "month")


def _validate(source: str, grain: str):
    if source not in db.DATE_COLS:
        raise ValueError(f"unknown source {source!r}")
    if grain not in GRAINS:
        raise ValueError(f"unknown grain {grain!r}")


def volume_sql(source: str, grain: str, role_id: str) -> str:
    """The statement, for display. Identifiers are allowlisted above; the date
    bounds are bound as parameters at execution, not interpolated."""
    _validate(source, grain)
    col = db.DATE_COLS[source]
    return (f"SELECT date_trunc('{grain}', {col}) AS bucket, COUNT(*) AS rows_ "
            f"FROM {source} WHERE {col} BETWEEN ? AND ?{db.role_where(role_id)} "
            "GROUP BY 1 ORDER BY 1")


@lru_cache(maxsize=256)
def _volume(source: str, grain: str, role_id: str, start: str, end: str):
    sql = volume_sql(source, grain, role_id)
    return sql, db.query(sql, (start, end))


def volume(source: str, grain: str, role_id: str, start, end):
    """Cached per (source, grain, role, window): the Data page re-renders on
    every widget touch, and on a warehouse each of these is a round trip."""
    sql, df = _volume(source, grain, role_id, str(start), str(end))
    return sql, df.copy()


@lru_cache(maxsize=256)
def _latest_rows(source: str, role_id: str, start: str, end: str, limit: int):
    _validate(source, "day")
    col = db.DATE_COLS[source]
    sql = (f"SELECT * FROM {source} WHERE {col} BETWEEN ? AND ?"
           f"{db.role_where(role_id)} ORDER BY {col} DESC LIMIT {int(limit)}")
    return sql, db.query(sql, (start, end))


def latest_rows(source: str, role_id: str, start, end, limit: int = 50):
    sql, df = _latest_rows(source, role_id, str(start), str(end), int(limit))
    return sql, df.copy()
