"""The watcher: proactive drafting, never proactive sending."""
import csv
import random

import pytest

import feedback as fb
from ops import ingest, watch
from services import outbox

PERIOD, ROLE = "2026-07", "analyst"


@pytest.fixture(autouse=True)
def clean():
    fb.reset_ledger()
    outbox.reset()
    ingest.reset()
    yield
    outbox.reset()
    ingest.reset()
    fb.reset_ledger()


def test_watcher_drafts_for_every_material_movement_and_only_once(llm):
    first = watch.portfolio_pass(PERIOD, ROLE, llm)
    msgs = outbox.messages()
    assert first and len(msgs) == len(first)
    kpis = {m["kpi"] for m in msgs}
    # the three ACTIONS verdicts route to lever owners; the abstention escalates to the KPI owner
    assert {"fulfilment_sla", "complaint_rate", "enterprise_active_accounts", "marketing_conversion"} <= kpis
    assert "aov" not in kpis, "a movement inside normal variation must not be drafted"
    assert all(m["actor"] == watch.ACTOR for m in msgs)
    assert all(m["status"] == outbox.DRAFT for m in msgs), "the watcher drafts; it never sends"
    second = watch.portfolio_pass(PERIOD, ROLE, llm)
    assert second == [] and len(outbox.messages()) == len(first)


def test_abstention_is_escalated_to_the_kpi_owner_not_instructed(llm):
    watch.portfolio_pass(PERIOD, ROLE, llm)
    esc = [m for m in outbox.messages() if m["kpi"] == "marketing_conversion"]
    assert esc and all(m["kind"] == "escalation" for m in esc)
    assert esc[0]["to"] == "Head of Growth Marketing"


def _write_live(n_ok: int, n_bad: int):
    ingest.ensure_lane()
    rng = random.Random(7)          # ops.ingest.emit uses the stdlib generator
    with open(ingest.EVENTS, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ingest.FIELDS)
        for i in range(n_ok + n_bad):
            w.writerow(ingest.emit(rng, degraded=i >= n_ok))


def test_live_breach_is_escalated_once_per_day():
    _write_live(10, 40)
    first = watch.live_pass()
    assert len(first) == 1
    m = next(x for x in outbox.messages() if x["id"] == first[0])
    assert m["kind"] == "escalation" and m["to"] == "VP Operations" and m["outcome"] == "live_breach"
    assert m["status"] == outbox.DRAFT and m["actor"] == watch.ACTOR
    assert "SLA breach" in m["subject"]
    assert watch.live_pass() == [], "the same breach on the same day is not drafted twice"


def test_healthy_lane_raises_nothing():
    _write_live(40, 0)
    assert watch.live_pass() == []


def test_run_once_records_itself(llm):
    s = watch.run_once(PERIOD, ROLE, llm)
    assert s["actor"] == watch.ACTOR and len(s["drafted"]) >= 4
    import store
    assert store.read("watch")[-1]["drafted"] == s["drafted"]
