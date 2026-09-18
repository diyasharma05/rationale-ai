"""The five planted scenarios, end to end.

This replaces smoke_test.py, which printed all of this and asserted none of it
-- it would have passed unchanged if every z-score flipped sign or every KPI
returned no_signal.
"""
import pytest

from engine import db, pyramid

PERIOD = "2026-07"


@pytest.fixture(scope="module")
def investigate(llm):
    def run(kpi_id, role="analyst", period=PERIOD):
        return pyramid.investigate(kpi_id, period, role, llm)
    return run


def test_golden_path_is_tentative_with_the_right_lead(investigate):
    """Revenue: the engine should find the WH-07 fulfilment story but stop
    short of asserting a root cause -- its own signal is marginal (p~0.07)."""
    r = investigate("revenue")
    assert r["outcome"] == "tentative"
    assert 0.60 <= r["confidence"]["value"] < 0.75
    top = next(h for h in r["hypotheses"] if h["rank"] == 1)
    assert top["driver_id"] == "fulfilment_sla"
    assert r["contribution"]["focus_regions"] == ["North-West"]


def test_planted_measurement_artifact_does_not_corroborate(investigate):
    """marketing_conversion has the largest |z| of any revenue driver but is a
    tracking bug. It must rank last and be flagged as unexplained."""
    r = investigate("revenue")
    mc = next(h for h in r["hypotheses"] if h["driver_id"] == "marketing_conversion")
    assert mc["unexplained"] is True
    assert mc["rank"] == max(h["rank"] for h in r["hypotheses"])


def test_abstain_path(investigate):
    """Both declared drivers are quiet and nothing corroborates a cause."""
    r = investigate("marketing_conversion")
    assert r["outcome"] == "abstain"
    assert r["confidence"]["value"] < 0.60
    assert r["narrative"]["actions"] == []
    assert r["narrative"]["clarifying_question"]


def test_sparse_path_makes_no_causal_claim(investigate):
    r = investigate("home_decor_revenue")
    assert r["outcome"] == "sparse"
    assert r["hypotheses"] == []
    assert str(r["confidence"]["value"]) in r["narrative"]["caveats"], \
        "the stated cap must quote the number actually scored"


def test_no_signal_path_is_the_noise_filter(investigate):
    r = investigate("aov")
    assert r["outcome"] == "no_signal"
    assert r["narrative"]["actions"] == []


def test_fulfilment_sla_reaches_actions(investigate):
    """The one case with an overwhelming signal and corroborating documents."""
    r = investigate("fulfilment_sla")
    assert r["outcome"] == "actions"
    assert r["confidence"]["value"] >= 0.75


@pytest.mark.parametrize("role", ["analyst", "ceo", "sales_head_north"])
def test_no_narrative_is_ever_empty(investigate, role):
    """The sanitizer used to strip the offline template narrative down to
    'Confidence 78%.' because the template contained 'z='."""
    for kpi_id in db.allowed_kpis(role):
        r = investigate(kpi_id, role=role)
        assert r["narrative"]["body"].strip(), f"empty narrative for {role}/{kpi_id}"
        assert len(r["narrative"]["body"]) > 40


def test_executive_never_sees_a_standardised_score(investigate):
    for kpi_id in db.allowed_kpis("ceo"):
        r = investigate(kpi_id, role="ceo")
        blob = r["narrative"]["headline"] + " " + r["narrative"]["body"]
        assert "z=" not in blob, f"z-score leaked to the executive via {kpi_id}"


def test_confidence_never_claims_certainty(investigate):
    for role in ("analyst", "ceo", "sales_head_north"):
        for kpi_id in db.allowed_kpis(role):
            v = investigate(kpi_id, role=role)["confidence"]["value"]
            assert v < 0.95, f"{role}/{kpi_id} reported {v}"
