"""Record mock-mode fixtures from one real Claude run.

Runs every demo-relevant (KPI x persona) investigation live; llm/client.py
auto-saves each response as llm/fixtures/<task>.json. After this, the full
demo works offline with MOCK_MODE=1.

Run: python record_fixtures.py   (requires ANTHROPIC_API_KEY)
"""
import json
import os

os.environ["RECORD_FIXTURES"] = "1"   # only this script may write fixtures

import feedback
import telemetry
from engine import pyramid
from llm.client import LLMClient

PERIOD = "2026-07"
RUNS = [
    ("revenue", "analyst"),
    ("revenue", "ceo"),
    ("revenue", "sales_head_north"),
    ("marketing_conversion", "analyst"),
    ("marketing_conversion", "ceo"),
    ("fulfilment_sla", "analyst"),
    ("complaint_rate", "analyst"),
    ("enterprise_active_accounts", "analyst"),
]

import sys

BRIEFINGS_ONLY = "--briefings-only" in sys.argv

llm = LLMClient()
assert llm.mode == "live", "Set ANTHROPIC_API_KEY (and MOCK_MODE!=1) to record fixtures."

feedback.reset_ledger()
for kpi, role in ([] if BRIEFINGS_ONLY else RUNS):
    r = pyramid.investigate(kpi, PERIOD, role, llm)
    print(f"{kpi:28s} as {role:18s} -> {r['outcome']:8s} conf={r['confidence']['value']:.2f} "
          f"| {r['narrative']['headline'][:70]}")

# --- morning briefings (one per persona) ---
from engine import anomaly, db
from llm import prompts

roles = db.load_roles()
for role_id in roles:
    persona = roles[role_id]["persona"]
    summary = []
    for kpi_id, cfg in db.allowed_kpis(role_id).items():
        s = db.kpi_series(kpi_id, role_id)
        an = anomaly.analyze(s, PERIOD, cfg["materiality"], cfg.get("min_history", 6))
        imp = ((an["current"] - an["mean"]) * 30 if cfg["unit"] == "INR/day"
               and an["current"] is not None and an["mean"] is not None else None)
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
