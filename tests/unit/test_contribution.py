"""Contribution decomposition: direction awareness and additivity."""
import pandas as pd

from engine import contribution, db


def table(**deltas):
    return pd.DataFrame({"member": list(deltas), "delta": list(deltas.values()),
                         "current": [0] * len(deltas), "baseline": [0] * len(deltas)})


def test_improving_member_is_not_a_focus_area():
    """Selecting on |share| put West into the complaint-rate focus because
    complaints FELL there -- and that region name then drove retrieval."""
    t = table(**{"North-West": 36.3, "West": -9.3, "South": -4.3})
    picked, kind = contribution.focus_members(t, good_direction="down")
    assert picked == ["North-West"]
    assert "West" not in picked
    assert kind == "concentrated"


def test_uniform_movement_reports_diffuse_not_an_arbitrary_pick():
    """All five regions within noise of each other: the old code picked
    whichever had the largest |delta|, a ~1% margin."""
    t = table(**{"West": -0.528, "East": -0.521, "North": -0.508,
                 "North-West": -0.492, "South": -0.482})
    picked, kind = contribution.focus_members(t, good_direction="up")
    assert picked == []
    assert kind == "diffuse"


def test_marketing_conversion_is_diffuse_in_the_real_data():
    cfg = db.allowed_kpis("analyst")["marketing_conversion"]
    res = contribution.top_contributors("marketing_conversion", cfg, "2026-07", "analyst")
    assert res["concentration"] == "diffuse"
    assert res["focus_regions"] == []


def test_non_additive_kpis_report_no_share():
    """Per-region percentage points do not sum to the shipment-weighted
    national delta, so a 'share of the movement' is not a quantity."""
    cfg = db.allowed_kpis("analyst")["fulfilment_sla"]
    res = contribution.top_contributors("fulfilment_sla", cfg, "2026-07", "analyst")
    assert res["additive"] is False
    assert res["tables"]["region"]["share_of_delta"].isna().all()


def test_shares_suppressed_when_offsetting_deltas_make_them_unstable():
    """complaint_rate is additive, but July's regional deltas largely cancel,
    which used to produce shares above 1 and negative shares."""
    cfg = db.allowed_kpis("analyst")["complaint_rate"]
    res = contribution.top_contributors("complaint_rate", cfg, "2026-07", "analyst")
    shares = res["tables"]["region"]["share_of_delta"]
    assert shares.isna().all() or ((shares.dropna().abs() <= 1.0).all())


def test_revenue_shares_are_well_behaved():
    cfg = db.allowed_kpis("analyst")["revenue"]
    res = contribution.top_contributors("revenue", cfg, "2026-07", "analyst")
    assert res["additive"] is True
    assert res["focus_regions"] == ["North-West"]
