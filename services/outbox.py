"""The outbox: drafted messages, human approval, then delivery.

Nothing leaves without a person clicking. The engine drafts and routes; a
human decides whether it goes. That ordering is deliberate — the product's
strongest property is that it declines to assert what it cannot support, and
an engine that messaged a VP off its own verdict would undo that.

Append-only, like the decision ledger: a draft, an approval and a send are
three events about one message, not three states overwritten in place. The
audit question "who sent this, and when did they approve it" has to be
answerable afterwards. Events go through store.py, so the outbox lives in the
same place as the ledger: JSONL by default, PostgreSQL when configured.
"""
import uuid
from datetime import datetime

import store
from engine import dispatch
from services import transports

STREAM = "outbox"

DRAFT, APPROVED, SENT, FAILED, CANCELLED = "draft", "approved", "sent", "failed", "cancelled"


def _append(event: dict):
    store.append(STREAM, event)


def _events():
    return [e for e in store.read(STREAM) if isinstance(e, dict)]


def reset():
    store.reset(STREAM)


def draft(result: dict, cfg: dict, actor: str) -> list:
    """Route a conclusion and queue the messages. Returns the drafted ids.

    Idempotent per (investigation, lever): clicking twice does not queue the
    same instruction twice, which matters when the thing being queued is an
    instruction to a person.
    """
    existing = {(m["investigation"], m["lever"]) for m in messages()}
    ids = []
    for msg in dispatch.route(result, cfg):
        key = (result.get("inv_id", ""), msg.lever)
        if key in existing:
            continue
        mid = f"MSG-{uuid.uuid4().hex[:8].upper()}"
        _append({"event": "draft", "id": mid,
                 "investigation": result.get("inv_id", ""),
                 "ts": datetime.now().isoformat(timespec="seconds"),
                 "actor": actor, **msg.as_dict()})
        ids.append(mid)
    return ids


def approve(message_id: str, actor: str, note: str = ""):
    _append({"event": "approve", "id": message_id, "actor": actor, "note": note,
             "ts": datetime.now().isoformat(timespec="seconds")})


def cancel(message_id: str, actor: str, reason: str = ""):
    _append({"event": "cancel", "id": message_id, "actor": actor, "reason": reason,
             "ts": datetime.now().isoformat(timespec="seconds")})


def send(message_id: str, transport=None) -> dict:
    """Deliver an APPROVED message. Refuses anything else."""
    msg = next((m for m in messages() if m["id"] == message_id), None)
    if msg is None:
        return {"ok": False, "detail": "no such message"}
    if msg["status"] != APPROVED:
        # the guard that makes "nothing leaves without a person" true rather
        # than merely intended
        return {"ok": False, "detail": f"message is {msg['status']}, not approved"}
    transport = transport or transports.get_transport()
    outcome = transport.send(msg)
    _append({"event": "sent" if outcome["ok"] else "failed", "id": message_id,
             "ts": datetime.now().isoformat(timespec="seconds"),
             "transport": outcome.get("transport"), "detail": outcome.get("detail")})
    return outcome


def messages() -> list:
    """Current state of every message, folded from the event log."""
    by_id = {}
    for e in _events():
        mid = e.get("id")
        if not mid:
            continue
        if e["event"] == "draft":
            m = {k: v for k, v in e.items() if k not in ("event",)}
            m["status"] = DRAFT
            m["history"] = [("draft", e.get("ts"), e.get("actor"))]
            by_id[mid] = m
        elif mid in by_id:
            m = by_id[mid]
            m["history"].append((e["event"], e.get("ts"), e.get("actor")))
            if e["event"] == "approve":
                m["status"] = APPROVED
                m["approved_by"] = e.get("actor")
                m["approval_note"] = e.get("note", "")
            elif e["event"] == "cancel":
                m["status"] = CANCELLED
            elif e["event"] == "sent":
                m["status"] = SENT
                m["sent_via"] = e.get("transport")
                m["sent_at"] = e.get("ts")
            elif e["event"] == "failed":
                m["status"] = FAILED
                m["error"] = e.get("detail")
    return list(by_id.values())


def summary() -> dict:
    counts = {DRAFT: 0, APPROVED: 0, SENT: 0, FAILED: 0, CANCELLED: 0}
    for m in messages():
        counts[m["status"]] = counts.get(m["status"], 0) + 1
    return counts
