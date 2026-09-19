"""Proactive alerts: a watcher that scans and drafts, and never sends.

The brief lists proactive alerts among the solutioning areas. The prototype
already detects, routes and dispatches, but only when a person clicks. This
process closes that gap without opening the one the design forbids:

    it SCANS  the portfolio for the analysis month (the same multiplicity-
              controlled scan the dashboard runs) and the live ingestion lane
              (the same rolling rule the Lineage page shows);
    it DRAFTS a message into the Outbox for every material movement that has
              none yet -- routed by the contract to the lever owner or the KPI
              owner, exactly as a clicked investigation would be;
    it never SENDS. Approval stays with a human, in the Outbox, every time.

Idempotent: a movement is drafted once per (KPI, period); a live breach once per
(regions, day). Every run is appended to the `watch` stream, so "what did the
watcher do overnight" is answerable from the ledger store.

    python -m ops.watch                     # one pass, then exit
    python -m ops.watch --interval 30       # poll every 30 s
    python -m ops.watch --period 2026-07 --role analyst
"""
import argparse
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("MOCK_MODE", "1")

import store                                            # noqa: E402
from engine import db, dispatch                         # noqa: E402
from services import live_ingest, outbox, scan          # noqa: E402

ACTOR = "watcher"
DEFAULT_PERIOD = "2026-07"
LIVE_KPI = "fulfilment_sla"


def portfolio_pass(period: str, role_id: str, llm) -> list:
    """Investigate every material KPI that has no message in the Outbox yet,
    and draft what the contract routes. Returns the drafted message ids."""
    from engine import pyramid
    already = {(m.get("kpi"), m.get("period")) for m in outbox.messages()}
    drafted = []
    for kpi_id, (cfg, _series, an) in scan.scan(role_id, period).items():
        if not an["material"] or (kpi_id, period) in already:
            continue
        result = pyramid.investigate(kpi_id, period, role_id, llm)
        drafted += outbox.draft(result, cfg, actor=ACTOR)
    return drafted


def live_pass(now: datetime = None) -> list:
    """Escalate a live-lane breach to the KPI owner, once per (regions, day)."""
    v = live_ingest.verdict()
    if not v.get("breached"):
        return []
    now = now or datetime.now()
    cfg = db.load_contract()["kpis"][LIVE_KPI]
    regions = ", ".join(sorted(v["breached"]))
    worst = max(v["regions"], key=lambda r: r["breach_rate"])
    body = "\n\n".join([
        f"The live monitor sees SLA breaches in {regions} over the trailing {v.get('window', 0)} events.",
        f"Worst region: {worst['region']} at {worst['breach_rate']:.0%} of shipments missing SLA "
        f"({int(worst['breaches'])} of {int(worst['shipments'])}).",
        "This is a rolling check on events as they arrive, not a monthly diagnosis; the "
        "investigation with evidence and confidence runs when the month closes, or on request.",
        f"Raised by the watcher at {now:%Y-%m-%d %H:%M}.",
    ])
    msg = dispatch.Message(
        kind=dispatch.KIND_ESCALATION, to=cfg.get("owner", dispatch.UNROUTED), cc="",
        channel="email", subject=f"[Rationale.AI] LIVE: SLA breach in {regions}",
        body=body, kpi=LIVE_KPI, kpi_name=cfg["name"], period=now.strftime("%Y-%m"),
        lever="", outcome="live_breach", confidence=0.0, requires_approval=False, evidence=[])
    mid = outbox.draft_message(msg, actor=ACTOR, dedupe_key=f"live:{regions}:{now:%Y-%m-%d}")
    return [mid] if mid else []


def run_once(period: str = DEFAULT_PERIOD, role_id: str = "analyst", llm=None) -> dict:
    if llm is None:
        from llm.client import LLMClient
        llm = LLMClient()
    t0 = time.perf_counter()
    drafted = portfolio_pass(period, role_id, llm)
    live = live_pass()
    summary = {"ts": datetime.now().isoformat(timespec="seconds"), "actor": ACTOR,
               "period": period, "role": role_id, "drafted": drafted, "live": live,
               "wall_ms": round((time.perf_counter() - t0) * 1000, 1)}
    store.append("watch", summary)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--period", default=DEFAULT_PERIOD)
    ap.add_argument("--role", default="analyst")
    ap.add_argument("--interval", type=float, default=0, help="seconds between passes; 0 = one pass")
    a = ap.parse_args(argv)
    import feedback
    feedback.ensure_state()
    while True:
        s = run_once(a.period, a.role)
        print(f"{s['ts']}  drafted {len(s['drafted'])} from the portfolio, {len(s['live'])} live "
              f"escalation(s), {s['wall_ms']:.0f} ms  -> approve or discard them in the Outbox")
        if not a.interval:
            break
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
