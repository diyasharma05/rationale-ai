"""Governed dispatch: turning a conclusion into a message someone receives.

The point of this module is what it does NOT do. It does not let the model
decide who gets told. Routing comes from the semantic contract -- the lever's
declared owner and approver -- exactly as the KPI definition comes from the
contract. The model writes the sentence inside the message; the contract
decides the envelope. That is the same split as "the LLM never computes a
number", one layer up: it never makes a routing decision either.

The outcome decides what gets sent, and to whom:

    actions     -> the lever owner, cc the approver, as an action
    tentative   -> the lever owner, framed as unconfirmed low-regret steps
    abstain     -> the KPI owner, as the Level-4 escalation brief
    no_signal   -> nobody. Silence is the correct output.
    sparse      -> nobody.

Pure: no I/O, no transport, no Streamlit. Queuing, approval and sending live
in services/outbox.py.
"""
from dataclasses import asdict, dataclass, field

from . import policy

# Only a conclusion that cleared the action gate may carry an instruction.
# Below it the engine may still ask for help, but it may not tell anyone what
# to do -- which is the whole abstention thesis, applied to the outbound path.
KIND_ACTION = "action"
KIND_LOW_REGRET = "low_regret"
KIND_ESCALATION = "escalation"

UNROUTED = policy.NO_OWNER


@dataclass(frozen=True)
class Message:
    """One outbound message, fully resolved. Nothing here is decided later."""
    kind: str
    to: str
    cc: str
    channel: str
    subject: str
    body: str
    kpi: str
    kpi_name: str
    period: str
    lever: str
    outcome: str
    confidence: float
    requires_approval: bool
    evidence: list = field(default_factory=list)

    def as_dict(self):
        return asdict(self)


def _evidence_ids(result: dict, limit: int = 3):
    return [s["id"] for s in (result.get("snippets") or [])[:limit]]


def _movement_line(result: dict) -> str:
    """The engine's own movement sentence -- already prose, already sanitized."""
    return (result.get("narrative", {}) or {}).get("headline", "").strip()


def _confidence_line(result: dict) -> str:
    """State the verdict honestly, in the message itself.

    A recipient acting on this needs to know whether the engine established a
    cause or merely suspects one. Burying that in the app would defeat the
    purpose of routing it to them at all.
    """
    conf = result["confidence"]["value"]
    outcome = result["outcome"]
    if outcome == "actions":
        return f"Confidence {conf:.0%} — cause established, evidence attached."
    if outcome == "tentative":
        return (f"Confidence {conf:.0%} — below the action threshold. Treat these as "
                "low-regret steps while the cause is confirmed, not as a diagnosis.")
    return f"Confidence {conf:.0%} — the engine could not establish a cause."


def route(result: dict, cfg: dict) -> list:
    """Every message this conclusion should produce. May be empty."""
    outcome = result["outcome"]
    if outcome in ("no_signal", "sparse"):
        return []                      # nothing happened; say nothing

    kpi_name = result.get("kpi_name", result["kpi"])
    conf = result["confidence"]["value"]
    narrative = result.get("narrative", {}) or {}
    evidence = _evidence_ids(result)

    if outcome == "abstain":
        brief = narrative.get("escalation_brief") or narrative.get("body", "")
        question = narrative.get("clarifying_question")
        body = "\n\n".join(filter(None, [
            _movement_line(result),
            brief,
            f"What the engine needs from a human: {question}" if question else None,
            _confidence_line(result),
        ]))
        return [Message(
            kind=KIND_ESCALATION,
            to=cfg.get("owner", UNROUTED),
            cc="",
            channel="email",
            subject=f"[Rationale.AI] {kpi_name}: needs a human — engine abstained",
            body=body,
            kpi=result["kpi"], kpi_name=kpi_name, period=result["period"],
            lever="", outcome=outcome, confidence=conf,
            requires_approval=False, evidence=evidence,
        )]

    kind = KIND_ACTION if outcome == "actions" else KIND_LOW_REGRET
    messages = []
    for action in narrative.get("actions") or []:
        lever_text = action.get("lever", "")
        lever = policy.lever_for(cfg, lever_text)
        # Owner and approver come from the contract, never from `action`,
        # which the model wrote.
        owner = lever.get("owner", UNROUTED) if lever else UNROUTED
        approval = lever.get("approval", UNROUTED) if lever else UNROUTED
        needs_approval = bool(lever) and approval not in (UNROUTED, "none") \
            and not str(approval).lower().startswith("none")
        body = "\n\n".join(filter(None, [
            _movement_line(result),
            f"Recommended: {action.get('action', '')}",
            f"Expected effect: {action.get('expected_impact')}"
            if action.get("expected_impact") else None,
            f"How we will know it worked: {action.get('monitoring')}"
            if action.get("monitoring") else None,
            f"Decision right: {approval}" if needs_approval
            else "Decision right: within this owner's remit.",
            _confidence_line(result),
            f"Evidence: {', '.join(evidence)}" if evidence else None,
        ]))
        prefix = "ACTION" if kind == KIND_ACTION else "FOR REVIEW"
        messages.append(Message(
            kind=kind,
            to=owner,
            cc=approval if needs_approval else "",
            channel="slack",
            subject=f"[Rationale.AI] {prefix} — {kpi_name} ({result['period']})",
            body=body,
            kpi=result["kpi"], kpi_name=kpi_name, period=result["period"],
            lever=lever["lever"] if lever else lever_text,
            outcome=outcome, confidence=conf,
            requires_approval=needs_approval, evidence=evidence,
        ))
    return messages


def undeliverable(messages) -> list:
    """Messages the contract could not route.

    Surfaced rather than dropped: an action with no owner is a gap in the
    contract, and that is worth showing a user instead of quietly discarding.
    """
    return [m for m in messages if m.to == UNROUTED]
