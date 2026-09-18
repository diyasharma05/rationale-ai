"""The abstain loop: the engine asks, a human answers, the engine re-investigates.

This is the one genuinely agentic addition, and it has to respect the thesis:
the human supplies a fact, the engine recomputes deterministically. These tests
pin that the answer is evidence with human provenance, that the hallucination
guard still applies to the MODEL, and that a ruled-out lead stays ruled out.
"""
import pytest

import feedback as fb
from engine import pyramid, retrieve

KPI, PERIOD, ROLE = "marketing_conversion", "2026-07", "analyst"


@pytest.fixture(autouse=True)
def clean():
    fb.reset_ledger()
    yield
    fb.reset_ledger()


def _ask(llm):
    r = pyramid.investigate(KPI, PERIOD, ROLE, llm)
    assert r["outcome"] == "abstain"
    assert r["narrative"]["clarifying_question"], "the abstain path must ask something"
    return r


def test_a_confirming_answer_changes_the_verdict(llm):
    before = _ask(llm)
    fb.log_answer(before["inv_id"], KPI, PERIOD, before["narrative"]["clarifying_question"],
                  "Yes — a checkout tracking change shipped on 3 July",
                  actor="head_of_growth", confirms=True)
    after = pyramid.investigate(KPI, PERIOD, ROLE, llm)
    assert after["outcome"] != "abstain"
    assert after["confidence"]["value"] > before["confidence"]["value"]


def test_the_human_cause_leads_and_carries_provenance(llm):
    before = _ask(llm)
    fb.log_answer(before["inv_id"], KPI, PERIOD, before["narrative"]["clarifying_question"],
                  "Yes — a checkout tracking change shipped on 3 July",
                  actor="head_of_growth", confirms=True)
    after = pyramid.investigate(KPI, PERIOD, ROLE, llm)
    top = next(h for h in after["hypotheses"] if h["rank"] == 1)
    assert top["source"] == "human"
    assert top["actor"] == "head_of_growth"
    assert top["snippets"], "the answer itself must be attached as evidence"
    kinds = {s["id"]: s["kind"] for s in after["snippets"]}
    assert all(kinds.get(sid) == "human_answer" for sid in top["snippets"])


def test_the_answer_is_retrieved_for_the_same_period(llm):
    """Engine precedent must be strictly past; a human answer is about THIS
    investigation and must be admissible now."""
    before = _ask(llm)
    fb.log_answer(before["inv_id"], KPI, PERIOD, "q", "Yes — tracking change",
                  actor="a", confirms=True)
    from engine import db
    cfg = db.load_contract()["kpis"][KPI]
    res = retrieve.search(cfg, [], [], ROLE, exclude_kpi=KPI, exclude_period=PERIOD)
    assert any(s["kind"] == "human_answer" for s in res["snippets"])


def test_an_answer_for_another_kpi_is_not_borrowed(llm):
    fb.log_answer("INV-X", "revenue", PERIOD, "q", "Yes — something", actor="a", confirms=True)
    from engine import db
    cfg = db.load_contract()["kpis"][KPI]
    res = retrieve.search(cfg, [], [], ROLE, exclude_kpi=KPI, exclude_period=PERIOD)
    assert not any(s["kind"] == "human_answer" for s in res["snippets"])


def test_ruling_out_keeps_the_abstention_and_records_who_checked(llm):
    before = _ask(llm)
    fb.log_answer(before["inv_id"], KPI, PERIOD, before["narrative"]["clarifying_question"],
                  "No — nothing changed in tracking this month",
                  actor="head_of_growth", confirms=False)
    after = pyramid.investigate(KPI, PERIOD, ROLE, llm)
    assert after["outcome"] == "abstain"
    assert after["eliminated_leads"] == [{"lead": "No — nothing changed in tracking this month",
                                          "actor": "head_of_growth"}]
    assert not any(h["source"] == "human" for h in after["hypotheses"])


def test_the_model_is_still_not_allowed_to_invent_a_cause(llm):
    """The guard blocks MODEL-proposed hypotheses when the contract declares
    drivers. A human answer must not open that door."""
    before = _ask(llm)
    fb.log_answer(before["inv_id"], KPI, PERIOD, "q", "Yes — tracking", actor="a", confirms=True)
    after = pyramid.investigate(KPI, PERIOD, ROLE, llm)
    assert all(h["source"] in ("driver", "human") for h in after["hypotheses"])


def test_a_human_cause_does_not_manufacture_actions(llm):
    """There is no contract lever for 'fix the tracking tag', so the engine
    must not invent one. TENTATIVE with no actions is the honest result."""
    before = _ask(llm)
    fb.log_answer(before["inv_id"], KPI, PERIOD, "q", "Yes — tracking", actor="a", confirms=True)
    after = pyramid.investigate(KPI, PERIOD, ROLE, llm)
    assert after["confidence"]["value"] < 0.95
    for a in after["narrative"].get("actions") or []:
        assert a.get("lever"), "an action with no contract lever is an invention"


def test_answered_investigation_does_not_replay_the_abstain_fixture(llm):
    """The recorded narrative for the unanswered case is abstain prose. After
    an answer the facts changed, so that fixture must not be shown."""
    before = _ask(llm)
    abstain_body = before["narrative"]["body"]
    fb.log_answer(before["inv_id"], KPI, PERIOD, "q", "Yes — tracking", actor="a", confirms=True)
    after = pyramid.investigate(KPI, PERIOD, ROLE, llm)
    assert after["narrative"]["body"] != abstain_body
