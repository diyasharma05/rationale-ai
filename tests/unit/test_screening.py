"""Multiplicity control. These tests pin the numbers the pitch quotes."""
import pytest

from engine import anomaly, db, screening


def bh(p, q):
    return screening.benjamini_hochberg(p, q)


def test_matches_published_bh_1995_example():
    """The worked example from Benjamini & Hochberg (1995): 4 rejections at q=0.05."""
    p = [0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298, 0.0344,
         0.0459, 0.3240, 0.4262, 0.5719, 0.6528, 0.7590, 1.000]
    reject, _ = bh(p, 0.05)
    assert sum(reject) == 4


def test_adjusted_pvalues_are_monotone_and_bounded():
    p = [0.2, 0.01, 0.3, 0.001, 0.9]
    _, adj = bh(p, 0.10)
    assert all(0.0 <= a <= 1.0 for a in adj)
    by_rank = [a for _, a in sorted(zip(p, adj))]
    assert by_rank == sorted(by_rank), "adjusted p-values must not decrease with rank"


def test_step_up_rejects_larger_p_below_the_cutoff():
    """BH is step-up: a p-value that fails its own threshold is still rejected
    when a larger-ranked one passes. This is what makes it more powerful than
    a per-test correction, so it is worth pinning."""
    p = [0.001, 0.0449, 0.0450]
    reject, _ = bh(p, 0.05)
    assert reject == [True, True, True]


def test_empty_input():
    assert bh([], 0.1) == ([], [])


@pytest.mark.parametrize("period,kpi", [
    ("2026-02", "complaint_rate"),
    ("2026-04", "complaint_rate"),
])
def test_known_false_positives_are_suppressed(period, kpi):
    """Both months flag on the per-KPI threshold with nothing planted. They are
    the reason multiplicity control exists; if either starts escalating again,
    detection precision has silently regressed."""
    cfg = db.allowed_kpis("analyst")[kpi]
    an = anomaly.analyze(db.kpi_series(kpi, "analyst"), period,
                         cfg["materiality"], cfg.get("min_history", 6))
    assert an["material"] is True, "expected this to clear the per-KPI bar"
    an = screening.screen(an, kpi, "analyst", period)
    assert an["material"] is False
    assert an["fdr_suppressed"] is True


def test_all_five_july_incidents_survive():
    planted = {"revenue", "fulfilment_sla", "complaint_rate",
               "enterprise_active_accounts", "marketing_conversion"}
    fam = screening.family_qvalues("analyst", "2026-07")
    survived = {k for k, v in fam.items() if v["significant"]}
    assert planted <= survived, f"multiplicity control suppressed a real incident: {planted - survived}"


def test_july_revenue_margin_is_thin_but_holds():
    """The demo's headline KPI clears FDR by ~0.001. The choice of q=0.10 is
    load-bearing and we say so on stage, so it gets a regression test: if this
    fails, the golden path has stopped being detected at all."""
    fam = screening.family_qvalues("analyst", "2026-07")
    rev = fam["revenue"]
    assert rev["significant"] is True
    assert rev["q_value"] < screening.FDR_Q
    assert rev["q_value"] > 0.05, "margin has moved; re-check the q=0.10 rationale"


def test_family_is_role_scoped():
    """Two roles monitor different numbers of KPIs, so the correction differs.
    A shared family would apply one role's denominator to another's tests."""
    a = screening.family_qvalues("analyst", "2026-07")
    s = screening.family_qvalues("sales_head_north", "2026-07")
    assert a["revenue"]["family_size"] != s["revenue"]["family_size"]
