"""Evaluation harness : does the engine actually get the right answer?

The synthetic generator plants known causes, so we have ground truth. This
scores the engine against it on four axes a sceptical stakeholder would ask
about, and writes the result to data/state/eval_results.json for the UI.

  1. Detection      : precision / recall of flagging the right KPIs
  2. Root cause     : does the top-ranked driver name the true cause?
  3. Abstention     : does it abstain exactly when evidence is missing?
  4. Calibration    : do high-confidence answers turn out correct?

Run:  python eval.py            (offline mode is fine and is the default)
"""
import json
import os
import statistics
import time

os.environ.setdefault("MOCK_MODE", "1")
# Score against a throwaway ledger: investigate() appends one entry per run,
# and the ledger is itself part of the Level-2 retrieval corpus — so without
# this, consecutive eval runs are not independent and the harness pollutes
# the very corpus it is measuring.
os.environ.setdefault("RATIONALE_STATE",
                      os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "data", "state", "_eval"))
# ... and keep that isolation when the analytics run on PostgreSQL: the numbers
# come from RATIONALE_DB, the scoring run's ledger stays on disk.
os.environ.setdefault("RATIONALE_STORE", "jsonl")

from engine import anomaly, confidence, db, pyramid, screening   # noqa: E402
from llm.client import LLMClient                 # noqa: E402

# Tracked (data/state/ is gitignored): the UI's evaluation panel must survive
# a fresh clone and a hosted deploy.
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "data", "eval_results.json")

# ---------------------------------------------------------------- ground truth
# What the generator actually planted. `cause` lists terms that must appear in
# the top-ranked driver or the narrative for the diagnosis to count as correct.
GROUND_TRUTH = {
    "2026-07": {                      # the incident month
        "label": "Incident month (WH-07 conveyor failure, competitor launch)",
        "flagged": {"revenue", "fulfilment_sla", "complaint_rate",
                    "enterprise_active_accounts", "marketing_conversion"},
        "normal": {"aov"},
        "sparse": {"home_decor_revenue"},
        "abstain": {"marketing_conversion"},          # planted tracking bug
        # The rank-1 hypothesis must be THIS driver. Substring-matching a bag
        # of terms was close to unfailable: the label is built from the
        # contract driver's own name ("Fulfilment SLA %" contains both "sla"
        # and "fulfil"), so it passed the moment any declared driver ranked
        # first. Naming the driver makes the test possible to fail.
        "cause_driver": {
            "revenue": "fulfilment_sla",
            "complaint_rate": "fulfilment_sla",
            "enterprise_active_accounts": "fulfilment_sla",
        },
        # fulfilment_sla declares no drivers, so its cause is LLM-proposed and
        # can only be checked on wording -- against the hypothesis LABEL only,
        # never the narrative body (in mock mode that body is a recorded
        # fixture which already names the cause, so scoring it would partly be
        # scoring a cached string).
        "cause": {
            "fulfilment_sla": ["wh-07", "conveyor", "warehouse", "sortation", "backlog"],
        },
        # The planted marketing tracking bug is a MEASUREMENT artifact, not a
        # cause of the revenue drop. It must never lead the explanation.
        "must_not_lead": {"revenue": "marketing_conversion"},
    },
}

# Control months : nothing was planted, so ANY flag is a false positive. Five
# of them, because a small easy control set flatters the score. 2026-02 is in
# specifically because it produced an uncounted false positive (complaint_rate,
# p=0.052) before multiplicity control. 2026-06 was previously excluded as
# ambiguous since the conveyor fails on the 25th; it is included now because
# six days of incident do not move the monthly aggregate past the bar
# (verified: zero flags), so it is a genuine control and not a free pass.
_CONTROL_KPIS = {"revenue", "aov", "fulfilment_sla", "complaint_rate",
                 "enterprise_active_accounts", "marketing_conversion"}
for _m in ("2026-02", "2026-03", "2026-04", "2026-05", "2026-06"):
    GROUND_TRUTH[_m] = {
        "label": "Control month (no incident planted)",
        "flagged": set(), "normal": set(_CONTROL_KPIS),
        "sparse": {"home_decor_revenue"}, "abstain": set(), "cause": {},
    }
ROLE = "analyst"


def _flag_state(kpi_id, cfg, period):
    an = anomaly.analyze(db.kpi_series(kpi_id, ROLE), period, cfg["materiality"],
                         cfg.get("min_history", 6))
    if an["sparse"]:
        return "sparse"
    # Score what the engine actually escalates, which includes multiplicity
    # control across the portfolio -- not the raw per-KPI threshold test.
    an = screening.screen(an, kpi_id, ROLE, period)
    return "flagged" if an["material"] else "normal"


def evaluate():
    llm = LLMClient()
    contract = db.load_contract()["kpis"]
    detection = {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "sparse_ok": 0, "sparse_total": 0}
    cases, cause_hits, cause_total = [], 0, 0
    abstain_ok = abstain_total = false_abstain = 0
    contained_fp = harmful_fp = 0
    latencies, llm_calls = [], []

    for period, gt in GROUND_TRUTH.items():
        # ---- 1. detection: compare the signal gate against ground truth ----
        for kpi_id, cfg in contract.items():
            state = _flag_state(kpi_id, cfg, period)
            if kpi_id in gt["sparse"]:
                detection["sparse_total"] += 1
                detection["sparse_ok"] += int(state == "sparse")
                continue
            should_flag = kpi_id in gt["flagged"]
            did_flag = state == "flagged"
            key = ("tp" if should_flag and did_flag else
                   "fn" if should_flag and not did_flag else
                   "fp" if did_flag else "tn")
            detection[key] += 1

        # ---- 2-4. run the full pyramid on every non-sparse KPI ----
        for kpi_id in sorted(gt["flagged"] | gt["normal"]):
            if kpi_id not in contract:
                continue
            t0 = time.perf_counter()
            r = pyramid.investigate(kpi_id, period, ROLE, llm)
            latencies.append((time.perf_counter() - t0) * 1000)
            llm_calls.append(len(r.get("telemetry", [])))
            outcome, conf = r["outcome"], r["confidence"]["value"]

            should_abstain = kpi_id in gt["abstain"]
            if should_abstain:
                abstain_total += 1
                abstain_ok += int(outcome == "abstain")
            elif outcome == "abstain" and kpi_id in gt["flagged"]:
                false_abstain += 1

            correct, note = None, ""
            terms = gt["cause"].get(kpi_id)
            want_driver = gt.get("cause_driver", {}).get(kpi_id)
            forbid_lead = gt.get("must_not_lead", {}).get(kpi_id)
            if want_driver or terms:
                cause_total += 1
                top = next((h for h in r["hypotheses"] if h.get("rank") == 1), None)
                top_driver = top.get("driver_id") if top else None
                if want_driver:
                    correct = top_driver == want_driver
                    note = (f"rank-1 is the planted cause ({want_driver})" if correct
                            else f"rank-1 was {top_driver}, expected {want_driver}")
                else:
                    label = (top["label"] if top else "").lower()
                    correct = any(t in label for t in terms)
                    note = ("rank-1 names the planted cause" if correct
                            else "planted cause not identified")
                if correct and forbid_lead and top_driver == forbid_lead:
                    correct = False
                    note = f"distractor {forbid_lead} led the explanation"
                cause_hits += int(correct)
            elif should_abstain:
                correct = outcome == "abstain"
                note = "correctly abstained" if correct else f"did not abstain ({outcome})"
            elif kpi_id in gt["normal"]:
                correct = outcome in ("no_signal", "sparse")
                if correct:
                    note = "correctly treated as noise"
                elif outcome in ("abstain", "sparse"):
                    contained_fp += 1
                    note = ("false alarm, but CONTAINED : the evidence gate refused "
                            "to state a cause")
                else:
                    harmful_fp += 1
                    note = f"false alarm that produced a conclusion ({outcome})"

            cases.append({"period": period, "kpi": kpi_id,
                          "kpi_name": contract[kpi_id]["name"], "outcome": outcome,
                          "confidence": conf, "correct": correct, "note": note})

    tp, fp, fn, tn = (detection[k] for k in ("tp", "fp", "fn", "tn"))
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    # ---- gate separation: are the thresholds FITTED or just asserted? ----
    # The honest test of a threshold is the margin around it. For each gate we
    # report the widest interval over which every case still lands in the right
    # band -- a wide interval means the exact value is not load-bearing, and a
    # narrow one is something to disclose rather than hide.
    should_conclude = [c["confidence"] for c in cases
                       if c["outcome"] in ("actions", "tentative")]
    should_not = [c["confidence"] for c in cases
                  if c["outcome"] in ("abstain", "no_signal")]
    gates = {
        "evidence_gate": {
            "value": confidence.EVIDENCE_GATE,
            "highest_below": round(max(should_not), 3) if should_not else None,
            "lowest_above": round(min(should_conclude), 3) if should_conclude else None,
        },
    }
    g = gates["evidence_gate"]
    if g["highest_below"] is not None and g["lowest_above"] is not None:
        g["margin"] = round(g["lowest_above"] - g["highest_below"], 3)
        g["safe_range"] = [g["highest_below"], g["lowest_above"]]
    acted = sorted(c["confidence"] for c in cases if c["outcome"] == "actions")
    tentative = sorted(c["confidence"] for c in cases if c["outcome"] == "tentative")
    gates["action_gate"] = {
        "value": confidence.ACTION_GATE,
        "highest_below": round(max(tentative), 3) if tentative else None,
        "lowest_above": round(min(acted), 3) if acted else None,
    }
    ga = gates["action_gate"]
    if ga["highest_below"] is not None and ga["lowest_above"] is not None:
        ga["margin"] = round(ga["lowest_above"] - ga["highest_below"], 3)
        ga["safe_range"] = [ga["highest_below"], ga["lowest_above"]]
    # ---- calibration: correctness within confidence bands ----
    bands = {"< 0.60 (abstain zone)": (0.0, 0.60),
             "0.60 – 0.75 (tentative)": (0.60, 0.75),
             ">= 0.75 (actions)": (0.75, 1.01)}
    calibration = []
    for name, (lo, hi) in bands.items():
        sel = [c for c in cases if c["correct"] is not None and lo <= c["confidence"] < hi]
        if sel:
            calibration.append({"band": name, "n": len(sel),
                                "accuracy": round(sum(c["correct"] for c in sel) / len(sel), 3),
                                "mean_confidence": round(
                                    statistics.mean(c["confidence"] for c in sel), 3)})

    scored = [c for c in cases if c["correct"] is not None]
    result = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "periods": {p: gt["label"] for p, gt in GROUND_TRUTH.items()},
        "detection": {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
                      "precision": round(precision, 3), "recall": round(recall, 3),
                      "f1": round(f1, 3),
                      "sparse_handled": f"{detection['sparse_ok']}/{detection['sparse_total']}"},
        "root_cause": {"hits": cause_hits, "total": cause_total,
                       "accuracy": round(cause_hits / cause_total, 3) if cause_total else None},
        "abstention": {"correct": abstain_ok, "expected": abstain_total,
                       "false_abstentions": false_abstain},
        "false_alarm_impact": {"contained": contained_fp, "harmful": harmful_fp},
        "overall": {"cases": len(scored),
                    "accuracy": round(sum(c["correct"] for c in scored) / len(scored), 3)
                    if scored else None},
        "calibration": calibration,
        "gates": gates,
        "runtime": {"median_ms": round(statistics.median(latencies), 1) if latencies else None,
                    "mean_llm_calls": round(statistics.mean(llm_calls), 2) if llm_calls else 0,
                    "mode": llm.mode},
        "cases": cases,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return result


def _print(r):
    d, rc, ab = r["detection"], r["root_cause"], r["abstention"]
    print(f"\n{'=' * 66}\n RATIONALE.AI : EVALUATION vs PLANTED GROUND TRUTH\n{'=' * 66}")
    print(f"\nDETECTION (signal gate)   precision {d['precision']:.0%} · "
          f"recall {d['recall']:.0%} · F1 {d['f1']:.2f}")
    print(f"                          TP {d['tp']} · FP {d['fp']} · FN {d['fn']} · TN {d['tn']}"
          f" · sparse handled {d['sparse_handled']}")
    if rc["accuracy"] is not None:
        print(f"ROOT CAUSE                {rc['hits']}/{rc['total']} correct "
              f"({rc['accuracy']:.0%})")
    print(f"ABSTENTION                {ab['correct']}/{ab['expected']} correct · "
          f"{ab['false_abstentions']} false abstentions")
    fa = r["false_alarm_impact"]
    print(f"FALSE ALARMS              {fa['contained']} contained by the evidence gate · "
          f"{fa['harmful']} produced a wrong conclusion")
    print(f"OVERALL                   {r['overall']['accuracy']:.0%} across "
          f"{r['overall']['cases']} scored cases")
    print("")
    print("GATE SEPARATION            (a wide margin means the threshold is not load-bearing)")
    for name, g in r["gates"].items():
        if g.get("margin") is None:
            print(f"  {name:24s} {g['value']:.2f}  (only one side observed)")
            continue
        print(f"  {name:24s} {g['value']:.2f}  margin {g['margin']:.3f} "
              f"(nothing between {g['safe_range'][0]:.3f} and {g['safe_range'][1]:.3f})")
    print(f"\nCALIBRATION")
    for c in r["calibration"]:
        print(f"  {c['band']:<26} n={c['n']:<3} accuracy {c['accuracy']:.0%} "
              f"(mean conf {c['mean_confidence']:.2f})")
    print(f"\nRUNTIME                   median {r['runtime']['median_ms']:.0f} ms · "
          f"{r['runtime']['mean_llm_calls']} LLM calls/investigation "
          f"({r['runtime']['mode']} mode)")
    bad = [c for c in r["cases"] if c["correct"] is False]
    if bad:
        print(f"\nFAILURES ({len(bad)}):")
        for c in bad:
            print(f"  {c['period']} {c['kpi']:<28} {c['outcome']:<10} {c['note']}")
    print(f"\nwritten to {OUT}\n")


# CI gate. Set from the current measured baseline: these are the numbers the
# pitch quotes, so a regression should fail a build rather than surface on
# stage. Recall and abstention are absolute -- missing a planted incident, or
# failing to abstain on the tracking bug, are the two failures that matter.
THRESHOLDS = {
    "detection.recall": 1.0,
    "detection.precision": 1.0,
    "root_cause.accuracy": 1.0,
    "overall.accuracy": 1.0,
}


def check(r: dict) -> int:
    failures = []
    for path, floor in THRESHOLDS.items():
        section, key = path.split(".")
        got = r[section][key]
        if got is None or got < floor:
            failures.append(f"{path}: {got} < {floor}")
    if r["abstention"]["correct"] < r["abstention"]["expected"]:
        failures.append("abstention: engine failed to abstain where it should")
    if r["false_alarm_impact"]["harmful"] > 0:
        failures.append("a false alarm produced a conclusion")
    if failures:
        print()
        print("EVAL CHECK FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print()
    print("EVAL CHECK PASSED : no regression against the recorded baseline.")
    return 0


if __name__ == "__main__":
    import sys
    result = evaluate()
    _print(result)
    if "--check" in sys.argv:
        sys.exit(check(result))
