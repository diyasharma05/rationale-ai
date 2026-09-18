"""Governed dispatch.

The claim being made on stage is not "it can send a Slack message" -- anyone
can do that. It is that routing comes from the contract, that nothing leaves
without a human, and that the engine stays silent when it has nothing to say.
Each of those is a test.
"""
import pytest

from engine import db, dispatch, pyramid
from services import outbox, transports

PERIOD = "2026-07"


@pytest.fixture(autouse=True)
def clean_outbox():
    outbox.reset()
    yield
    outbox.reset()


def investigate(llm, kpi):
    return pyramid.investigate(kpi, PERIOD, "analyst", llm), \
        db.load_contract()["kpis"][kpi]


def test_silence_when_there_is_nothing_to_say(llm):
    """no_signal and sparse must produce no messages at all. An engine that
    pings someone about a metric behaving normally is the alert fatigue this
    product exists to remove."""
    for kpi in ("aov", "home_decor_revenue"):
        r, cfg = investigate(llm, kpi)
        assert r["outcome"] in ("no_signal", "sparse")
        assert dispatch.route(r, cfg) == []


def test_recipient_comes_from_the_contract_not_the_model(llm):
    """The narrative also emits an `owner` field. It must be ignored: a
    model-chosen recipient is the same class of error as a model-computed
    number."""
    r, cfg = investigate(llm, "fulfilment_sla")
    for action in r["narrative"]["actions"]:
        action["owner"] = "(model invented this person)"
    for msg in dispatch.route(r, cfg):
        assert msg.to != "(model invented this person)"
        contract_owners = {lever["owner"] for lever in cfg["levers"]}
        assert msg.to in contract_owners


def test_approval_right_is_carried_from_the_contract(llm):
    r, cfg = investigate(llm, "fulfilment_sla")
    msgs = dispatch.route(r, cfg)
    assert msgs
    by_owner = {m.to: m for m in msgs}
    assert "VP Operations" in by_owner
    assert "COO" in by_owner["VP Operations"].cc


def test_tentative_is_labelled_as_unconfirmed(llm):
    """The golden path is TENTATIVE. A message that reads like an instruction
    would undo the restraint the verdict represents."""
    r, cfg = investigate(llm, "revenue")
    assert r["outcome"] == "tentative"
    msgs = dispatch.route(r, cfg)
    assert msgs and all(m.kind == dispatch.KIND_LOW_REGRET for m in msgs)
    body = msgs[0].body.lower()
    assert "below the action threshold" in body
    assert "not as a diagnosis" in body
    assert "FOR REVIEW" in msgs[0].subject


def test_abstain_escalates_to_a_human_instead_of_instructing_one(llm):
    r, cfg = investigate(llm, "marketing_conversion")
    assert r["outcome"] == "abstain"
    msgs = dispatch.route(r, cfg)
    assert len(msgs) == 1
    msg = msgs[0]
    assert msg.kind == dispatch.KIND_ESCALATION
    assert msg.to == cfg["owner"]
    assert "could not establish a cause" in msg.body
    assert msg.requires_approval is False


def test_nothing_sends_without_an_approval(llm):
    """The guard that makes 'a human decides' true rather than merely
    intended."""
    r, cfg = investigate(llm, "fulfilment_sla")
    ids = outbox.draft(r, cfg, actor="analyst")
    assert ids
    result = outbox.send(ids[0])
    assert result["ok"] is False
    assert "not approved" in result["detail"]
    assert next(m for m in outbox.messages() if m["id"] == ids[0])["status"] == "draft"


def test_approval_then_send_is_recorded_as_separate_events(llm):
    """'Who approved this, and when' has to be answerable afterwards."""
    r, cfg = investigate(llm, "fulfilment_sla")
    mid = outbox.draft(r, cfg, actor="analyst")[0]
    outbox.approve(mid, actor="ceo", note="cleared with ops")
    assert outbox.send(mid)["ok"] is True
    msg = next(m for m in outbox.messages() if m["id"] == mid)
    assert msg["status"] == "sent"
    assert msg["approved_by"] == "ceo"
    assert msg["approval_note"] == "cleared with ops"
    assert [h[0] for h in msg["history"]] == ["draft", "approve", "sent"]


def test_drafting_twice_does_not_queue_the_same_instruction_twice(llm):
    r, cfg = investigate(llm, "fulfilment_sla")
    first = outbox.draft(r, cfg, actor="analyst")
    second = outbox.draft(r, cfg, actor="analyst")
    assert first and second == []


def test_default_transport_does_not_deliver(monkeypatch):
    """Delivery is opt-in. The demo must not be one env var away from
    messaging real people."""
    monkeypatch.delenv("RATIONALE_DISPATCH", raising=False)
    t = transports.get_transport()
    assert t.live is False
    assert t.name == "dry-run"


def test_unroutable_action_is_surfaced_not_guessed():
    """An action whose lever has no contract owner has nobody to go to. That
    is a gap in the contract, not an invitation to pick someone."""
    result = {
        "kpi": "revenue", "kpi_name": "Net Revenue", "period": PERIOD,
        "outcome": "actions", "confidence": {"value": 0.9},
        "narrative": {"headline": "x", "actions": [
            {"action": "do a thing", "lever": "a lever nobody owns"}]},
        "snippets": [],
    }
    msgs = dispatch.route(result, {"levers": [], "owner": "Someone"})
    assert len(msgs) == 1
    assert msgs[0].to == dispatch.UNROUTED
    assert dispatch.undeliverable(msgs) == msgs
