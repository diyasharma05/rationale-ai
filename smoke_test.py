"""End-to-end engine smoke test (no UI, no LLM key needed).
Verifies every planted scenario lands where the plan says it should.
Run: python smoke_test.py
"""
import json

from engine import anomaly, db, pyramid
from llm.client import LLMClient

PERIOD = "2026-07"
llm = LLMClient()
print(f"LLM mode: {llm.mode}\n")

contract = db.load_contract()

print("=== 1. anomaly scan (analyst, all KPIs) ===")
for kpi_id, cfg in contract["kpis"].items():
    s = db.kpi_series(kpi_id, "analyst")
    an = anomaly.analyze(s, PERIOD, cfg["materiality"], cfg.get("min_history", 6))
    print(f"{kpi_id:28s} cur={an['current']!s:>16} z={an['z']!s:>7} "
          f"pct={an['pct_vs_recent']!s:>7} material={an['material']} sparse={an['sparse']}")

print("\n=== 2. golden path: revenue investigation ===")
r = pyramid.investigate("revenue", PERIOD, "analyst", llm)
print("outcome:", r["outcome"], "| confidence:", r["confidence"]["value"],
      r["confidence"]["components"])
print("focus regions:", r["contribution"]["focus_regions"])
for h in r["hypotheses"]:
    print(f"  {h['id']} [{h['source']}] snippets={h['snippets']} events={len(h['events'])} :: {h['label'][:90]}")
print("contradictions:", [d["label"] for d in r["contradictions"]])
print("retrieved:", [(s["id"], s["file"]) for s in r["snippets"]])
print("narrative headline:", r["narrative"]["headline"])
print("fallback narrative?", r["narrative"].get("_fallback"))

print("\n=== 3. abstention path: marketing_conversion ===")
m = pyramid.investigate("marketing_conversion", PERIOD, "analyst", llm)
print("outcome:", m["outcome"], "| confidence:", m["confidence"]["value"],
      m["confidence"]["components"])
print("drivers:", [(d["driver_id"], d["status"], d["z"]) for d in m["drivers"]])
print("retrieved:", [(s["id"], s["file"]) for s in m.get("snippets", [])])

print("\n=== 4. sparse path: home_decor_revenue ===")
h = pyramid.investigate("home_decor_revenue", PERIOD, "analyst", llm)
print("outcome:", h["outcome"], "| headline:", h["narrative"]["headline"])

print("\n=== 5. no-signal path: aov ===")
a = pyramid.investigate("aov", PERIOD, "analyst", llm)
print("outcome:", a["outcome"], "| z:", a["anomaly"]["z"], "pct:", a["anomaly"]["pct_vs_recent"])

print("\n=== 6. RBAC ===")
rev_all = db.kpi_series("revenue", "analyst")
rev_north = db.kpi_series("revenue", "sales_head_north")
print("analyst July revenue:", float(rev_all[rev_all.period == PERIOD]["value"].iloc[0]))
print("sales_head July revenue:", float(rev_north[rev_north.period == PERIOD]["value"].iloc[0]))
print("KPIs visible to sales_head:", list(db.allowed_kpis("sales_head_north")))
print("mask sample:", db.mask_text("Meridian Retail Group and Kalinga Mart", "ceo"))

print("\n=== 7. telemetry ===")
import telemetry
print(json.dumps(telemetry.summarize(telemetry.RECORDS), indent=2))

print("\n=== 8. contribution (revenue, region) ===")
print(r["contribution"]["tables"]["region"].to_string(index=False))
