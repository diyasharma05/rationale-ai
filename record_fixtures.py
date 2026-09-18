"""Record mock-mode fixtures from one real Claude run.

Runs every demo-relevant (KPI x persona) investigation live; llm/client.py
auto-saves each response as llm/fixtures/<task>.json. After this, the full
demo works offline with MOCK_MODE=1.

Run: python record_fixtures.py   (requires ANTHROPIC_API_KEY)
"""
import json
import os

os.environ["RECORD_FIXTURES"] = "1"   # only this script may write fixtures

# Headlines contain rupee signs; a Windows console defaults to cp1252 and would
# crash the run partway through -- after the API calls have been paid for.
import io
import sys as _sys
if hasattr(_sys.stdout, "buffer"):
    _sys.stdout = io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8", errors="replace")

import feedback
import telemetry
from engine import pyramid
from llm.client import LLMClient

PERIOD = "2026-07"
# Every (KPI, role) combination that reaches the narrative call in the demo
# month. Derived by sweeping the engine, not by hand: five of these were
# missing before, so a judge clicking a flagged CEO tile fell through to the
# offline template. The Live Feed alarm button deep-links straight into one
# of them.
RUNS = [
    ("revenue", "analyst"),
    ("fulfilment_sla", "analyst"),
    ("complaint_rate", "analyst"),
    ("enterprise_active_accounts", "analyst"),
    ("marketing_conversion", "analyst"),
    ("revenue", "ceo"),
    ("fulfilment_sla", "ceo"),
    ("complaint_rate", "ceo"),
    ("enterprise_active_accounts", "ceo"),
    ("marketing_conversion", "ceo"),
    ("revenue", "sales_head_north"),
    ("fulfilment_sla", "sales_head_north"),
    ("complaint_rate", "sales_head_north"),
]

import sys

BRIEFINGS_ONLY = "--briefings-only" in sys.argv
SKIP_BRIEFINGS = "--no-briefings" in sys.argv
# --resume re-records only what is missing. Every call costs money, so a
# crash partway through should not mean paying for the whole set again.
RESUME = "--resume" in sys.argv

FIX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "llm", "fixtures")


def _already(kpi, role):
    persona = __import__("engine.db", fromlist=["db"]).load_roles()[role]["persona"]
    return os.path.exists(os.path.join(FIX_DIR, f"narrative_{kpi}_{persona}.json"))

llm = LLMClient()
assert llm.mode == "live", "Set ANTHROPIC_API_KEY (and MOCK_MODE!=1) to record fixtures."

feedback.reset_ledger()
for kpi, role in ([] if BRIEFINGS_ONLY else RUNS):
    if RESUME and _already(kpi, role):
        print(f"{kpi:28s} as {role:18s} -> already recorded, skipping")
        continue
    r = pyramid.investigate(kpi, PERIOD, role, llm)
    print(f"{kpi:28s} as {role:18s} -> {r['outcome']:8s} conf={r['confidence']['value']:.2f} "
          f"| {r['narrative']['headline'][:70]}")

# --- morning briefings (one per persona) ---
from engine import anomaly, db, economics
from llm import prompts

roles = db.load_roles()
for role_id in ([] if SKIP_BRIEFINGS else roles):
    persona = roles[role_id]["persona"]
    summary = []
    for kpi_id, cfg in db.allowed_kpis(role_id).items():
        s = db.kpi_series(kpi_id, role_id)
        an = anomaly.analyze(s, PERIOD, cfg["materiality"], cfg.get("min_history", 6))
        imp = economics.monthly_impact(an, cfg["unit"])
        summary.append({"kpi": cfg["name"],
                        "status": "flagged" if an["material"] else ("sparse" if an["sparse"] else "normal"),
                        "value": an["current"], "change_pct": an["pct_vs_recent"], "z": an["z"],
                        "monthly_impact_inr": imp})
    summary.sort(key=lambda r: (r["status"] != "flagged", -(abs(r["z"] or 0))))
    b = llm.json_call(f"briefing_{persona}", prompts.BRIEFING_SYSTEM,
                      prompts.build_briefing_prompt(summary, persona,
                                                    roles[role_id].get("narrative_style", ""), PERIOD),
                      model="claude-sonnet-5", max_tokens=6000, effort="low")
    print(f"briefing_{persona:16s} -> {(b or {}).get('greeting', 'FAILED')[:60]}")

feedback.reset_ledger()  # leave a clean ledger for the demo
print("\nTelemetry:", json.dumps(telemetry.summarize(telemetry.RECORDS), indent=2))
print("Fixtures saved to llm/fixtures/. Demo is now offline-safe (MOCK_MODE=1).")
