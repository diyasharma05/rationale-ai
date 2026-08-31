"""Live-feed replay : turns the seeded historical data into an event stream that
can be replayed in accelerated time, so the UI can show data arriving and the
engine catching an incident as it happens.

Nothing here is random or LLM-driven: the cursor walks real rows, and the
breach test is the same statistical rule the batch engine uses (rolling window
vs a pre-window baseline, ±z threshold).
"""
from datetime import date, timedelta
from functools import lru_cache

import pandas as pd

from . import db

# the replay opens a few days before the WH-07 conveyor failure (2026-06-25) so
# a viewer sees a healthy stream first, then the incident develop
REPLAY_START = date(2026, 6, 18)
REPLAY_END = date(2026, 7, 31)
ROLL_DAYS = 7          # rolling window the live monitor evaluates
BASELINE_DAYS = 60     # trailing window the rolling value is judged against
BREACH_Z = 2.0


def clamp(d: date) -> date:
    return max(REPLAY_START, min(REPLAY_END, d))


@lru_cache(maxsize=8)
def _daily_region(role_id: str) -> pd.DataFrame:
    """One row per (day, region): orders, revenue, shipments, breaches, complaints.
    Monitoring is dimensional — a regional incident must not be diluted by the
    national total, which is exactly how it would hide in a real business."""
    where = db.role_where(role_id)
    sql = f"""
    WITH o AS (SELECT CAST(order_date AS DATE) d, region, COUNT(*) orders,
                      SUM(order_value) revenue
               FROM sales_orders WHERE 1=1 {where} GROUP BY 1,2),
         f AS (SELECT CAST(ship_date AS DATE) d, region, SUM(shipments) shipments,
                      SUM(sla_breaches) breaches
               FROM ops_fulfilment WHERE 1=1 {where} GROUP BY 1,2),
         c AS (SELECT CAST(event_date AS DATE) d, region, COUNT(*) complaints
               FROM crm_events WHERE event_type='complaint' {where} GROUP BY 1,2)
    SELECT o.d AS day, o.region, o.orders, o.revenue,
           COALESCE(f.shipments,0) shipments, COALESCE(f.breaches,0) breaches,
           COALESCE(c.complaints,0) complaints
    FROM o LEFT JOIN f ON o.d=f.d AND o.region=f.region
           LEFT JOIN c ON o.d=c.d AND o.region=c.region ORDER BY 1,2"""
    df = db.get_conn().execute(sql).fetchdf()
    df["day"] = pd.to_datetime(df["day"]).dt.date
    return df


@lru_cache(maxsize=8)
def _daily(role_id: str) -> pd.DataFrame:
    """National roll-up of the per-region stream (volume charts, totals)."""
    df = _daily_region(role_id).groupby("day", as_index=False)[
        ["orders", "revenue", "shipments", "breaches", "complaints"]].sum()
    return df.sort_values("day").reset_index(drop=True)


def totals_to(cursor: date, role_id: str) -> dict:
    """Cumulative volume ingested since the replay opened."""
    d = _daily(role_id)
    w = d[(d["day"] >= REPLAY_START) & (d["day"] <= cursor)]
    return {"days": len(w), "orders": int(w["orders"].sum()),
            "revenue": float(w["revenue"].sum()),
            "shipments": int(w["shipments"].sum()),
            "complaints": int(w["complaints"].sum()),
            "events": int(w["orders"].sum() + w["shipments"].sum() + w["complaints"].sum())}


def series_to(cursor: date, role_id: str) -> pd.DataFrame:
    """Per-day volume + rolling monitored metrics, up to the cursor."""
    d = _daily(role_id).copy()
    d = d[d["day"] <= cursor]
    d["sla"] = 100 * (1 - d["breaches"] / d["shipments"].replace(0, pd.NA))
    d["sla_roll"] = d["sla"].rolling(ROLL_DAYS, min_periods=3).mean()
    d["rev_roll"] = d["revenue"].rolling(ROLL_DAYS, min_periods=3).mean()
    d["cmp_roll"] = d["complaints"].rolling(ROLL_DAYS, min_periods=3).mean()
    return d[d["day"] >= REPLAY_START - timedelta(days=ROLL_DAYS)]


# metric key -> (label, column, unit, direction that is BAD)
MONITORED = {
    "fulfilment_sla": ("Fulfilment SLA", "sla_roll", "%", "down"),
    "revenue": ("Revenue run-rate", "rev_roll", "INR", "down"),
    "complaints": ("Complaints / day", "cmp_roll", "count", "up"),
}


def live_status(cursor: date, role_id: str) -> list:
    """Evaluate each monitored metric at the cursor, PER REGION, and report the
    worst region: rolling 7-day value vs that region's own pre-replay baseline,
    using the same z-rule as the batch signal gate."""
    d = _daily_region(role_id).copy()
    d["sla"] = 100 * (1 - d["breaches"] / d["shipments"].replace(0, pd.NA))
    base = d[(d["day"] < REPLAY_START) & (d["day"] >= REPLAY_START - timedelta(days=BASELINE_DAYS))]
    roll = d[(d["day"] <= cursor) & (d["day"] > cursor - timedelta(days=ROLL_DAYS))]
    out = []
    if roll.empty or base.empty:
        return out
    src_of = {"fulfilment_sla": "sla", "revenue": "revenue", "complaints": "complaints"}
    for key, (label, _col, unit, bad_dir) in MONITORED.items():
        src = src_of[key]
        worst = None
        for region, rb in base.groupby("region"):
            rr = roll[roll["region"] == region]
            if rr.empty or len(rb) < 10:
                continue
            mean = float(rb[src].astype(float).mean())
            sd = float(rb[src].astype(float).std(ddof=1) or 1e-9)
            cur = float(rr[src].astype(float).mean())
            z = (cur - mean) / sd
            severity = -z if bad_dir == "down" else z
            if worst is None or severity > worst["severity"]:
                worst = {"region": region, "current": cur, "baseline": mean,
                         "z": round(z, 2), "severity": severity,
                         "pct": round((cur - mean) / abs(mean) * 100, 1) if mean else 0.0}
        if worst is None:
            continue
        out.append({"key": key, "label": label, "unit": unit,
                    "region": worst["region"], "current": worst["current"],
                    "baseline": worst["baseline"], "z": worst["z"], "pct": worst["pct"],
                    "breached": bool(worst["severity"] >= BREACH_Z)})
    return out


def recent_events(cursor: date, role_id: str, days_back: int = 3, limit: int = 14) -> list:
    """The event ticker: real rows landing in the last few simulated days."""
    where = db.role_where(role_id)
    lo = cursor - timedelta(days=days_back - 1)
    rows = []
    crm = db.get_conn().execute(f"""
        SELECT event_date d, region, event_type, account_name, note FROM crm_events
        WHERE CAST(event_date AS DATE) BETWEEN DATE '{lo}' AND DATE '{cursor}'
          AND event_type IN ('complaint','churn') {where}
        ORDER BY CAST(event_date AS DATE) DESC LIMIT 40""").fetchdf()
    for _, r in crm.iterrows():
        if r["event_type"] == "churn":
            rows.append({"day": str(r["d"]), "sev": "high", "kind": "CHURN",
                         "text": f"Account closed : {db.mask_text(str(r['account_name']), role_id)}"
                                 f" ({r['region']})"})
        else:
            rows.append({"day": str(r["d"]), "sev": "warn", "kind": "COMPLAINT",
                         "text": f"{str(r['note']).capitalize()} · {r['region']}"})
    ops = db.get_conn().execute(f"""
        SELECT ship_date d, region, shipments, sla_breaches FROM ops_fulfilment
        WHERE CAST(ship_date AS DATE) BETWEEN DATE '{lo}' AND DATE '{cursor}'
          AND sla_breaches > 0 {where}
        ORDER BY sla_breaches DESC LIMIT 12""").fetchdf()
    for _, r in ops.iterrows():
        rate = r["sla_breaches"] / max(int(r["shipments"]), 1)
        rows.append({"day": str(r["d"]), "sev": "warn" if rate > 0.15 else "info",
                     "kind": "FULFILMENT",
                     "text": f"{int(r['sla_breaches'])} of {int(r['shipments'])} shipments "
                             f"missed SLA · {r['region']}"})
    orders = db.get_conn().execute(f"""
        SELECT order_date d, region, segment, order_value, account FROM sales_orders
        WHERE CAST(order_date AS DATE) BETWEEN DATE '{lo}' AND DATE '{cursor}'
          AND segment = 'enterprise' {where}
        ORDER BY order_value DESC LIMIT 10""").fetchdf()
    for _, r in orders.iterrows():
        acct = str(r["account"]).split("|")[-1] if r["account"] else "—"
        rows.append({"day": str(r["d"]), "sev": "info", "kind": "ORDER",
                     "text": f"Enterprise order ₹{r['order_value']:,.0f} · "
                             f"{db.mask_text(acct, role_id)} ({r['region']})"})
    rows.sort(key=lambda x: x["day"], reverse=True)
    return rows[:limit]
