"""Confidence scoring invariants. The point of these is that a future tweak to
the maths cannot silently restore an over-claim."""
from engine import confidence


def drivers(*statuses, unexplained=()):
    return [{"status": s, "unexplained": i in unexplained}
            for i, s in enumerate(statuses)]


def hyps(n_corroborated, n_total):
    return [{"snippets": ["E1"] if i < n_corroborated else [], "events": []}
            for i in range(n_total)]


def test_cannot_reach_one_even_when_everything_is_perfect():
    """The old formulation returned exactly 1.000 for enterprise_active_accounts
    and displayed it as 100% confidence on a single month of n~11 data."""
    s = confidence.score(99.0, drivers("co_moves", "co_moves", "co_moves"), hyps(3, 3))
    assert s["value"] < 1.0
    assert s["value"] <= confidence.MAX_CONFIDENCE


def test_one_of_one_is_not_certainty():
    """Laplace smoothing: a single corroborated hypothesis is 2/3, not 1.0."""
    assert confidence.evidence_agreement(hyps(1, 1)) == 2 / 3


def test_no_hypotheses_scores_zero_not_smoothed():
    """Nothing to corroborate is an absence of evidence. Smoothing it would
    hand out free credit for having found no explanation at all."""
    assert confidence.evidence_agreement([]) == 0.0


def test_no_declared_drivers_is_unassessable_not_half_marks():
    """The old code returned a flat 0.5 'neutral prior', i.e. 0.175 of the total
    score for having nothing to check."""
    assert confidence.driver_coverage([]) is None
    s = confidence.score(9.0, [], hyps(1, 1))
    assert s["components"]["coverage"] is None
    assert s["assessed"] == ["evidence", "signal"]


def test_unverifiable_does_not_outscore_verified():
    """Renormalising alone had a perverse consequence: dropping a checkable
    dimension RAISED the score. A KPI we could cross-check against drivers must
    not score below an otherwise-identical one we could not check at all."""
    checked = confidence.score(9.0, drivers("co_moves"), hyps(1, 1))
    unchecked = confidence.score(9.0, [], hyps(1, 1))
    assert unchecked["breadth"] < checked["breadth"]
    assert unchecked["value"] < checked["value"]


def test_unexplained_driver_counts_for_less():
    """A driver that moved but that nothing upstream explains is a lead. This
    is what keeps the planted marketing tracking bug from corroborating."""
    solid = confidence.score(5.0, drivers("co_moves", "co_moves"), hyps(2, 2))
    shaky = confidence.score(5.0, drivers("co_moves", "co_moves", unexplained={1}), hyps(2, 2))
    assert shaky["value"] < solid["value"]


def test_contradicting_driver_reduces_coverage():
    with_contra = confidence.driver_coverage(drivers("co_moves", "contradicts"))
    without = confidence.driver_coverage(drivers("co_moves", "quiet"))
    assert with_contra < without


def test_sparse_cap_is_reachable():
    """SPARSE_CAP used to be dead code -- score() was never called with
    sparse=True, so the documented 0.40 cap could never apply."""
    s = confidence.score(99.0, drivers("co_moves"), hyps(1, 1), sparse=True)
    assert s["sparse_capped"] is True
    assert s["value"] == confidence.SPARSE_CAP


def test_gates_are_ordered():
    assert confidence.EVIDENCE_GATE < confidence.ACTION_GATE < confidence.MAX_CONFIDENCE
