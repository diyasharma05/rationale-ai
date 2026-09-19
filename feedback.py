"""Feedback capture + decision ledger. Every completed investigation is
appended to the ledger; the ledger is part of the Level-2 retrieval corpus,
so past conclusions and user corrections inform future runs (the deck's
"Recall" step and the learning loop).

Storage goes through store.py: JSONL files under data/state/ by default, or a
PostgreSQL events table when RATIONALE_DB points at one. Nothing here knows
which; every record is an event appended to a named stream.
"""
import os
from datetime import datetime

import store

BASE = os.path.dirname(os.path.abspath(__file__))
# Kept for anything that still reasons about the JSONL layout (RATIONALE_STATE
# lets tests and eval.py point at a throwaway directory, so a test run never
# appends to the ledger it is measuring). The store decides whether these
# paths are actually in use.
STATE = os.environ.get("RATIONALE_STATE") or os.path.join(BASE, "data", "state")
LEDGER = os.path.join(STATE, "decision_ledger.jsonl")
FEEDBACK = os.path.join(STATE, "feedback.jsonl")

LEDGER_STREAM, FEEDBACK_STREAM = "decision_ledger", "feedback"


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
    """Restore the ledger to its seed state (demo reset).

    On an append-only PostgreSQL store this is an operator action; the
    application role can seed an empty stream but not clear a populated one,
    and store.reset raises PermissionError to say so.
    """
    store.reset(LEDGER_STREAM, [SEED_ENTRY])
    store.reset(FEEDBACK_STREAM)


def ensure_state():
    """Seed the ledger if it is missing.

    data/state/ is gitignored, so a fresh clone (and every hosted deploy) starts
    with no ledger at all. That silently changes Level-2 retrieval — the seeded
    Nov-2025 precedent drops out of the corpus and the [E#] ranks shift — so the
    same fixture can cite a different document than it did on the dev laptop.
    Seeding at boot keeps every machine on the same corpus. Appends rather than
    resets, so it works for a role that may only INSERT.
    """
    if not store.exists(LEDGER_STREAM):
        store.append(LEDGER_STREAM, SEED_ENTRY)


def log_investigation(result: dict) -> str:
    inv_id = f"INV-{result['period']}-{result['kpi'].upper()}-{datetime.now().strftime('%H%M%S')}"
    store.append(LEDGER_STREAM, {
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


def log_feedback(inv_id: str, vote: str, comment: str = "", kpi: str = "",
                 period: str = "", driver: str = ""):
    """Record a human judgement ON an existing investigation.

    Written as a VERDICT record keyed to the original entry, not as a new
    pseudo-investigation. The old mirror row was a ledger entry with
    kpi="feedback", period="" and confidence="" -- which put a non-numeric
    value in the confidence column (breaking its dtype) and created a row that
    no period filter could ever exclude from the retrieval corpus.
    """
    rec = {"id": inv_id, "timestamp": datetime.now().isoformat(timespec="seconds"),
           "vote": vote, "comment": comment, "kpi": kpi, "period": period,
           "driver": driver}
    store.append(FEEDBACK_STREAM, rec)
    store.append(LEDGER_STREAM, {"type": "verdict", "id": f"{inv_id}#verdict",
                                 "target": inv_id, "timestamp": rec["timestamp"],
                                 "kpi": kpi, "period": period, "driver": driver,
                                 "vote": vote, "comment": comment})


def log_answer(inv_id: str, kpi: str, period: str, question: str, answer: str,
               actor: str, confirms=None) -> str:
    """A human answers the question the engine asked when it abstained.

    This is the input the abstain path was missing: the engine stopped, asked,
    and the answer went nowhere. Stored as an event on the investigation, like a
    verdict, so it is auditable -- and surfaced to retrieval as a document with
    HUMAN provenance, so a re-run can use it as evidence.

    `confirms` is True when the human confirms the suspected cause, False when
    they rule it out, None for information that does neither.
    """
    ts = datetime.now().isoformat(timespec="seconds")
    rec = {"type": "answer", "id": f"{inv_id}#answer-{ts.replace(':', '')}",
           "target": inv_id, "timestamp": ts, "actor": actor, "kpi": kpi,
           "period": period, "question": question, "answer": answer,
           "confirms": confirms}
    store.append(LEDGER_STREAM, rec)
    return rec["id"]


def answers_for(kpi: str, period: str) -> list:
    """Human answers recorded against this KPI and period, oldest first."""
    return [e for e in read_ledger(include_verdicts=True)
            if e.get("type") == "answer" and e.get("kpi") == kpi
            and e.get("period") == period]


def read_ledger(include_verdicts: bool = False):
    """Investigations, with any human verdict folded in.

    The stream is append-only, so a vote arrives as a separate `verdict` record
    pointing at an existing id; reading folds it back onto the investigation
    it judges. Callers therefore see one row per investigation carrying its
    latest vote, rather than a stream of orphan feedback rows.
    """
    entries, verdicts = [], {}
    for rec in store.read(LEDGER_STREAM):
        if not isinstance(rec, dict):
            continue
        if rec.get("type") == "verdict":
            verdicts[rec.get("target")] = rec      # last vote wins
            if include_verdicts:
                entries.append(rec)
        elif rec.get("type") == "answer":
            if include_verdicts:                     # answers are events too
                entries.append(rec)
        else:
            entries.append(rec)
    for e in entries:
        v = verdicts.get(e.get("id"))
        if v:
            e["feedback"] = v.get("vote")
            e["correction"] = v.get("comment", "")
        # The seeded precedent stores feedback as a nested object, while
        # verdicts store a bare vote string. Normalise so every consumer can
        # treat `feedback` as "up" | "down" | None.
        if isinstance(e.get("feedback"), dict):
            e["correction"] = e["feedback"].get("comment", "")
            e["feedback"] = e["feedback"].get("vote")
    return entries


def verdicts_by_kpi(kpi: str) -> list:
    """Every human verdict recorded against this KPI, newest last."""
    return [e for e in read_ledger(include_verdicts=True)
            if e.get("type") == "verdict" and e.get("kpi") == kpi]
