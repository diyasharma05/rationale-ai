"""Latency and concurrency benchmark.

Two jobs:

1. `--latency` : per-stage timings for one investigation, so the numbers in
   the UI and the deck come from a stopwatch rather than from memory.
2. `--concurrency` : p50/p95 against N concurrent investigations, which is the
   evidence behind "stateless, so add replicas". Runs the engine in threads
   against the shared DuckDB handle -- which is precisely the path that has to
   be thread-safe, so this doubles as a correctness check.

Run:  python -m ops.bench --json
"""
import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("MOCK_MODE", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import feedback                                    # noqa: E402
from engine import anomaly, contribution, db, drivers, pyramid, retrieve, screening  # noqa: E402
from llm.client import LLMClient                   # noqa: E402

PERIOD = "2026-07"
ROLE = "analyst"
# Budgets the demo is held to. Exceeding one should fail a nightly build, not
# be discovered on stage.
BUDGET_MS = {"scan": 250, "investigate_warm": 1500, "investigate_p95": 4000}


def _time(fn, n=5):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000)
    return round(min(ts), 1), round(statistics.median(ts), 1)


def latency():
    cfg = db.allowed_kpis(ROLE)["revenue"]
    series = db.kpi_series("revenue", ROLE)
    an = anomaly.analyze(series, PERIOD, cfg["materiality"], 6)
    llm = LLMClient()

    stages = {}
    stages["kpi_series"] = _time(lambda: db.kpi_series("revenue", ROLE))
    stages["portfolio_scan"] = _time(lambda: [
        anomaly.analyze(db.kpi_series(k, ROLE), PERIOD, c["materiality"], c.get("min_history", 6))
        for k, c in db.allowed_kpis(ROLE).items()])
    stages["fdr_family"] = _time(lambda: screening.family_qvalues(ROLE, PERIOD))
    stages["contribution"] = _time(lambda: contribution.top_contributors("revenue", cfg, PERIOD, ROLE))
    stages["drivers"] = _time(lambda: drivers.check_drivers(cfg, an["z"], PERIOD, ROLE, parent_series=series))
    stages["retrieval"] = _time(lambda: retrieve.search(cfg, ["North-West"], [], ROLE, exclude_period=PERIOD))
    stages["investigate"] = _time(lambda: pyramid.investigate("revenue", PERIOD, ROLE, llm), n=3)
    return {k: {"min_ms": v[0], "median_ms": v[1]} for k, v in stages.items()}


def concurrency(levels=(1, 2, 4, 8, 16), per_level=16):
    """Fire N investigations at once and report the latency distribution.

    Correctness matters as much as speed here: every worker shares one DuckDB
    handle, so a wrong answer under load would mean the cursor-per-call
    pattern is not holding.
    """
    llm = LLMClient()
    pyramid.investigate("revenue", PERIOD, ROLE, llm)        # warm caches first
    baseline = pyramid.investigate("revenue", PERIOD, ROLE, llm)["confidence"]["value"]

    out = []
    for n in levels:
        lat, wrong = [], 0

        def one(_):
            t0 = time.perf_counter()
            r = pyramid.investigate("revenue", PERIOD, ROLE, llm)
            return (time.perf_counter() - t0) * 1000, r["confidence"]["value"]

        with ThreadPoolExecutor(max_workers=n) as pool:
            t0 = time.perf_counter()
            for ms, conf in pool.map(one, range(per_level)):
                lat.append(ms)
                wrong += int(abs(conf - baseline) > 1e-9)
            wall = time.perf_counter() - t0

        lat.sort()
        out.append({
            "concurrency": n,
            "requests": per_level,
            "p50_ms": round(statistics.median(lat), 1),
            "p95_ms": round(lat[max(0, int(len(lat) * 0.95) - 1)], 1),
            "throughput_rps": round(per_level / wall, 1),
            "wrong_answers": wrong,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--skip-concurrency", action="store_true")
    ap.add_argument("--check", action="store_true", help="exit 1 if a budget is breached")
    args = ap.parse_args()

    feedback.reset_ledger()
    report = {"latency": latency()}
    if not args.skip_concurrency:
        report["concurrency"] = concurrency()
    feedback.reset_ledger()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("\nPER-STAGE LATENCY (warm)")
        for stage, v in report["latency"].items():
            print(f"  {stage:18s} {v['median_ms']:8.1f} ms")
        if "concurrency" in report:
            print("\nCONCURRENCY (same engine, shared DuckDB handle)")
            print(f"  {'N':>3s} {'p50 ms':>9s} {'p95 ms':>9s} {'req/s':>8s}  wrong")
            for row in report["concurrency"]:
                print(f"  {row['concurrency']:3d} {row['p50_ms']:9.1f} {row['p95_ms']:9.1f} "
                      f"{row['throughput_rps']:8.1f}  {row['wrong_answers']}")

    if args.check:
        bad = []
        inv = report["latency"]["investigate"]["median_ms"]
        scan = report["latency"]["portfolio_scan"]["median_ms"]
        if scan > BUDGET_MS["scan"]:
            bad.append(f"portfolio_scan {scan}ms > {BUDGET_MS['scan']}ms")
        if inv > BUDGET_MS["investigate_warm"]:
            bad.append(f"investigate {inv}ms > {BUDGET_MS['investigate_warm']}ms")
        for row in report.get("concurrency", []):
            if row["wrong_answers"]:
                bad.append(f"{row['wrong_answers']} wrong answers at concurrency {row['concurrency']}")
        if bad:
            print("\nBENCH CHECK FAILED:")
            for b in bad:
                print(f"  - {b}")
            return 1
        print("\nBENCH CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
