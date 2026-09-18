"""The learning loop, tested where it has to be real: does a human correction
change a later answer?

Before this existed, an upvote and a downvote scored identically -- feedback
was text the model might read, no gate or rank was affected, and the UI still
promised that corrections would shape future investigations.
"""
import pytest

import feedback as fb
from engine import pyramid, retrieve


@pytest.fixture(autouse=True)
def clean():
    fb.reset_ledger()
    yield
    fb.reset_ledger()


def _run(llm, kpi="revenue"):
    return pyramid.investigate(kpi, "2026-07", "analyst", llm)


def test_a_correction_demotes_the_explanation_it_rejects(llm):
    first = _run(llm)
    top = next(h for h in first["hypotheses"] if h["rank"] == 1)
    before = top["strength"]

    fb.log_feedback(first["inv_id"], "down", "not the cause",
                    kpi="revenue", period="2026-07", driver=top["driver_id"])

    second = _run(llm)
    same = next(h for h in second["hypotheses"] if h["driver_id"] == top["driver_id"])
    assert same["strength"] < before
    assert same["precedent"] == "down"
    assert same["rank"] > 1, "a rejected explanation should no longer lead"


def test_a_confirmation_promotes_it(llm):
    first = _run(llm)
    weak = sorted(first["hypotheses"], key=lambda h: h["strength"])[1]
    before = weak["strength"]

    fb.log_feedback(first["inv_id"], "up", "confirmed by ops",
                    kpi="revenue", period="2026-07", driver=weak["driver_id"])

    second = _run(llm)
    same = next(h for h in second["hypotheses"] if h["driver_id"] == weak["driver_id"])
    assert same["strength"] > before
    assert same["precedent"] == "up"


def test_the_verdict_is_folded_onto_the_investigation_it_judges(llm):
    r = _run(llm)
    fb.log_feedback(r["inv_id"], "down", "wrong region", kpi="revenue",
                    period="2026-07", driver="fulfilment_sla")
    entry = next(e for e in fb.read_ledger() if e["id"] == r["inv_id"])
    assert entry["feedback"] == "down"
    assert entry["correction"] == "wrong region"


def test_feedback_never_writes_a_non_numeric_confidence(llm):
    """The old mirror row wrote confidence="" into the ledger, which broke the
    column's dtype as soon as anyone voted."""
    r = _run(llm)
    fb.log_feedback(r["inv_id"], "up", "", kpi="revenue", period="2026-07")
    for e in fb.read_ledger():
        c = e.get("confidence")
        assert c is None or isinstance(c, (int, float)), f"non-numeric confidence: {c!r}"


def test_a_rejected_conclusion_is_not_reused_as_evidence(llm):
    """Precedent a human marked wrong is actively harmful, so it is dropped
    from the retrieval corpus rather than merely down-weighted."""
    assert retrieve.VOTE_WEIGHT["down"] == 0.0
    assert retrieve.VOTE_WEIGHT["up"] > retrieve.VOTE_WEIGHT[None]


def test_outcomes_that_skip_the_full_pyramid_are_still_logged(llm):
    """no_signal and sparse used to return before the ledger write, so 20 of
    24 eval cases never appeared -- while the page claimed every investigation
    is appended."""
    for kpi in ("aov", "home_decor_revenue"):
        r = pyramid.investigate(kpi, "2026-07", "analyst", llm)
        assert r["outcome"] in ("no_signal", "sparse")
        assert r.get("inv_id"), f"{kpi} ({r['outcome']}) was not logged"
        assert any(e["id"] == r["inv_id"] for e in fb.read_ledger())
