"""Live ingestion: a second process writing rows the app has never seen.

Why this exists. The Live Feed is a REPLAY -- it walks rows that were already
in the dataset when the app started. That proves the detector works; it does
not prove the ingestion path is real. This does: another process appends
events now, and the app picks them up within a poll interval and runs the same
rolling detector over them.

Deliberately writes to its own lane (data/live/) rather than into the demo
tables. Mutating sales_orders mid-demo would invalidate the recorded fixtures
and move the golden path's numbers, and a live-data story is not worth putting
the main narrative at risk.

    python -m ops.ingest                      # steady, healthy traffic
    python -m ops.ingest --inject-anomaly 30  # degrade SLA after 30 events
    python -m ops.ingest --reset              # clear the lane and exit
"""
import argparse
import csv
import json
import os
import pathlib
import random
import time
from datetime import datetime, timedelta

LIVE_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "live"
EVENTS = LIVE_DIR / "events.csv"
STATUS = LIVE_DIR / "status.json"

FIELDS = ["ts", "region", "order_value", "shipments", "sla_breaches", "complaints"]
REGIONS = ["North", "North-West", "South", "East", "West"]

# Healthy baseline, matched to the seeded dataset so the live lane looks like
# the same business rather than a different one.
BASE_ORDER = 5200
BASE_SHIPMENTS = 14
BASE_BREACH_RATE = 0.06
BASE_COMPLAINT_RATE = 0.05


def ensure_lane():
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    if not EVENTS.exists():
        with open(EVENTS, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(FIELDS)


def reset():
    for p in (EVENTS, STATUS):
        if p.exists():
            p.unlink()
    print(f"live lane cleared: {LIVE_DIR}")


def emit(rng, degraded: bool):
    """One event. Degraded mode raises the SLA breach and complaint rate in
    North-West only -- the same shape as the planted WH-07 incident, so the
    live detector has something real to catch."""
    region = rng.choice(REGIONS)
    hot = degraded and region == "North-West"
    shipments = max(1, int(rng.gauss(BASE_SHIPMENTS, 3)))
    breach_rate = 0.42 if hot else BASE_BREACH_RATE
    complaint_rate = 0.30 if hot else BASE_COMPLAINT_RATE
    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "region": region,
        "order_value": round(max(0.0, rng.gauss(BASE_ORDER * (0.72 if hot else 1.0), 900)), 2),
        "shipments": shipments,
        "sla_breaches": sum(1 for _ in range(shipments) if rng.random() < breach_rate),
        "complaints": sum(1 for _ in range(shipments) if rng.random() < complaint_rate),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, default=2.0, help="events per second")
    ap.add_argument("--inject-anomaly", type=int, default=None, metavar="N",
                    help="degrade North-West after N events")
    ap.add_argument("--count", type=int, default=0, help="stop after N events (0 = forever)")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    if args.reset:
        reset()
        return 0

    ensure_lane()
    rng = random.Random(args.seed)
    delay = 1.0 / max(args.rate, 0.1)
    n, started = 0, datetime.now()
    print(f"ingesting to {EVENTS} at ~{args.rate}/s  (ctrl-c to stop)")
    try:
        while True:
            degraded = args.inject_anomaly is not None and n >= args.inject_anomaly
            row = emit(rng, degraded)
            with open(EVENTS, "a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, FIELDS).writerow(row)
            n += 1
            # a tiny sidecar so the UI can show liveness without parsing the
            # whole file on every poll
            STATUS.write_text(json.dumps({
                "events": n,
                "started": started.isoformat(timespec="seconds"),
                "last": row["ts"],
                "degraded": degraded,
                "rate_per_s": args.rate,
            }), encoding="utf-8")
            if degraded and n == args.inject_anomaly:
                print(f"  [{n}] North-West degraded : SLA breaches and complaints rising")
            elif n % 25 == 0:
                print(f"  [{n}] events")
            if args.count and n >= args.count:
                break
            time.sleep(delay)
    except KeyboardInterrupt:
        print(f"\nstopped after {n} events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
