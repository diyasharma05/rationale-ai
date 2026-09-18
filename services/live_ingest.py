"""Read the live ingestion lane and score it with the same rule as the batch engine.

The lane is written by `python -m ops.ingest` in a separate process. Nothing
here is cached: the whole point is to read what exists right now.
"""
import json
import pathlib

import pandas as pd

LIVE_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "live"
EVENTS = LIVE_DIR / "events.csv"
STATUS = LIVE_DIR / "status.json"

# Same shape of test the batch engine runs: a recent window judged against the
# window before it. Small here because the live lane is seconds old, not months.
WINDOW = 40
BREACH_SLA = 0.20        # share of shipments missing SLA
MIN_FOR_VERDICT = 20


def status() -> dict:
    """Writer liveness, from the sidecar the ingest process maintains."""
    try:
        return json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def events(limit: int = None) -> pd.DataFrame:
    if not EVENTS.exists():
        return pd.DataFrame(columns=["ts", "region", "order_value", "shipments",
                                     "sla_breaches", "complaints"])
    try:
        df = pd.read_csv(EVENTS)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        # the writer may be mid-append; a partial read is not an error here
        return pd.DataFrame(columns=["ts", "region", "order_value", "shipments",
                                     "sla_breaches", "complaints"])
    return df.tail(limit) if limit else df


def verdict() -> dict:
    """Per-region SLA over the trailing window, and whether it breaches.

    Returns `assessable: False` until enough events have arrived, rather than
    rendering a confident number off three rows -- the same discipline the
    batch engine applies with its sparse-history guard.
    """
    df = events()
    out = {"total": len(df), "assessable": False, "regions": [], "breached": []}
    if df.empty:
        return out
    recent = df.tail(WINDOW)
    out["window"] = len(recent)
    if len(recent) < MIN_FOR_VERDICT:
        out["note"] = (f"{len(recent)} of {MIN_FOR_VERDICT} events needed before "
                       "the live monitor will call anything")
        return out
    out["assessable"] = True
    g = recent.groupby("region", as_index=False).agg(
        shipments=("shipments", "sum"),
        breaches=("sla_breaches", "sum"),
        complaints=("complaints", "sum"),
        revenue=("order_value", "sum"),
        events=("region", "size"))
    g["breach_rate"] = g["breaches"] / g["shipments"].clip(lower=1)
    g = g.sort_values("breach_rate", ascending=False)
    out["regions"] = g.to_dict("records")
    out["breached"] = [r["region"] for r in out["regions"]
                       if r["breach_rate"] >= BREACH_SLA]
    return out
