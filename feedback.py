"""Feedback capture + decision ledger. Every completed investigation is
appended to the ledger; the ledger is part of the Level-2 retrieval corpus,
so past conclusions and user corrections inform future runs (the deck's
"Recall" step and the learning loop).
"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, "data", "state")
LEDGER = os.path.join(STATE, "decision_ledger.jsonl")
FEEDBACK = os.path.join(STATE, "feedback.jsonl")


def _append(path: str, obj: dict):
    os.makedirs(STATE, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, default=str) + "\n")


# Pre-seeded precedent: the Nov-2025 East dispatch incident (powers "Recall")
SEED_ENTRY = {
    "id": "INV-2025-11-EAST", "timestamp": "2025-11-28T10:00:00",
    "kpi": "fulfilment_sla", "period": "2025-11", "confidence": 0.82,
    "outcome": "actions",
    "summary": "East region SLA breaches rose to 15% during festive peak; root cause sorter "
               "capacity. Temporary 3PL overflow capacity recovered SLA in 12 days.",
    "feedback": {"vote": "up", "comment": "3PL playbook worked; pre-approve next time."},
}


def reset_ledger():
    """Restore the ledger to its seed state (demo reset)."""
    os.makedirs(STATE, exist_ok=True)
    with open(LEDGER, "w", encoding="utf-8") as f:
        f.write(json.dumps(SEED_ENTRY) + "\n")
    if os.path.exists(FEEDBACK):
        os.remove(FEEDBACK)


def log_investigation(result: dict) -> str:
    inv_id = f"INV-{result['period']}-{result['kpi'].upper()}-{datetime.now().strftime('%H%M%S')}"
    _append(LEDGER, {
        "id": inv_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "kpi": result["kpi"], "period": result["period"],
        "confidence": result["confidence"]["value"],
        "outcome": result["outcome"],
        "summary": (result.get("narrative", {}) or {}).get("headline", "")
                   + " — " + (result.get("narrative", {}) or {}).get("body", "")[:300],
        "feedback": None,
    })
    return inv_id


def log_feedback(inv_id: str, vote: str, comment: str = ""):
    _append(FEEDBACK, {"id": inv_id, "timestamp": datetime.now().isoformat(timespec="seconds"),
                       "vote": vote, "comment": comment})
    # also mirror the correction into the ledger so retrieval can surface it
    _append(LEDGER, {
        "id": f"{inv_id}-FB", "timestamp": datetime.now().isoformat(timespec="seconds"),
        "kpi": "feedback", "period": "", "confidence": "",
        "outcome": f"user_{vote}",
        "summary": f"User feedback on {inv_id}: {vote}. {comment}".strip(),
        "feedback": vote,
    })


def read_ledger():
    if not os.path.exists(LEDGER):
        return []
    with open(LEDGER, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]
