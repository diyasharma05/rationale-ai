"""The three solutioning areas added for the finale: a causal estimate that is
honest about identification, the contract as a traversable knowledge graph, and
a forward view stated with its width."""
import pytest

from engine import anomaly, causal, contribution, db, economics, forecast, graph

PERIOD = "2026-07"


def _an(kpi, role="analyst"):
    cfg = db.load_contract()["kpis"][kpi]
    series = db.kpi_series(kpi, role)
    an = anomaly.analyze(series, PERIOD, cfg["materiality"], cfg.get("min_history", 6))
    contrib = contribution.top_contributors(kpi, cfg, PERIOD, role)
    return cfg, series, an, contrib


# ---------------------------------------------------------------- causal

def test_regional_shock_yields_an_identifiable_negative_effect_with_an_interval():
    cfg, series, an, contrib = _an("revenue")
    est = causal.estimate("revenue", PERIOD, "analyst", contrib["focus_regions"], an)
    assert est["identifiable"] and est["treated"] == ["North-West"]
    assert est["effect"] < 0 and est["ci95"][0] < est["effect"] < est["ci95"][1]
    assert est["ci_excludes_zero"], "the planted shock is large; the interval should not span zero"
    assert est["unit"] == "INR/day" and est["monthly_effect"] < 0
    assert set(est["controls"]) == {"East", "North", "South", "West"}
    assert est["placebo"]["floor"] == 0.2, "with four placebo regions the permutation p cannot go below 0.2"


def test_sla_effect_is_in_percentage_points_and_negative():
    cfg, series, an, contrib = _an("fulfilment_sla")
    est = causal.estimate("fulfilment_sla", PERIOD, "analyst", contrib["focus_regions"], an)
    assert est["identifiable"] and est["unit"] == "%"
    assert est["effect"] < -5, est          # 92% -> 88% nationally is ~ -12 pp in the one treated region


def test_a_national_movement_is_not_identifiable_and_says_why():
    """The planted tracking bug hits every region: no untreated comparison
    group exists, and the honest answer is to say so rather than estimate."""
    cfg, series, an, contrib = _an("marketing_conversion")
    assert contrib.get("concentration") == "diffuse"
    est = causal.estimate("marketing_conversion", PERIOD, "analyst", contrib["focus_regions"], an)
    assert not est["identifiable"] and "no untreated comparison group" in est["reason"]


def test_a_kpi_without_a_regional_panel_is_not_identifiable():
    est = causal.estimate("enterprise_active_accounts", PERIOD, "analyst", ["North-West"], None)
    assert not est["identifiable"] and "no regional panel" in est["reason"]


def test_restricted_role_gets_a_weak_controls_warning():
    """The sales head sees two regions; with one control the design still
    runs, and the output says the interval deserves caution."""
    cfg, series, an, contrib = _an("revenue", "sales_head_north")
    est = causal.estimate("revenue", PERIOD, "sales_head_north", contrib["focus_regions"], an)
    assert est["identifiable"] and est["controls"] == ["North"] and est["weak_controls"]
    assert "caution" in causal.summary_line(est)


def test_estimate_is_deterministic():
    cfg, series, an, contrib = _an("revenue")
    a = causal.estimate("revenue", PERIOD, "analyst", contrib["focus_regions"], an)
    b = causal.estimate("revenue", PERIOD, "analyst", contrib["focus_regions"], an)
    assert a == b


def test_summary_line_states_the_assumption_check():
    cfg, series, an, contrib = _an("revenue")
    line = causal.summary_line(causal.estimate("revenue", PERIOD, "analyst", contrib["focus_regions"], an))
    assert "Difference-in-differences" in line and "parallel trends" in line and "95% CI" in line


# ---------------------------------------------------------------- graph

def test_contract_graph_has_every_node_type_and_no_dangling_edges():
    g = graph.build(db.load_contract())
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])
    c = graph.counts(g)
    assert c["kpi"] == 7 and c["system"] == 3 and c["source"] == 4
    assert c["lever"] >= 9 and c["owner"] >= 5 and c["approver"] >= 4 and c["metric"] == 2


def test_downstream_reads_the_declared_driver_edges_in_reverse():
    c = db.load_contract()
    down = {d["kpi"]: d["relation"] for d in graph.downstream(c, "fulfilment_sla")}
    assert down == {"revenue": "direct", "complaint_rate": "inverse", "enterprise_active_accounts": "direct"}
    assert graph.downstream(c, "revenue") == []                 # nothing declares revenue as a driver
    assert [u["id"] for u in graph.upstream(c, "revenue")] == [
        "fulfilment_sla", "complaint_rate", "enterprise_active_accounts", "marketing_conversion"]


def test_exposure_names_the_owners_a_movement_touches():
    ex = graph.exposure(db.load_contract(), "fulfilment_sla")
    owners = {o["owner"] for o in ex["owners"]}
    assert {"VP Operations", "Head of Enterprise Sales", "Head of Customer Service"} <= owners
    assert all(o["levers"] for o in ex["owners"])


# ---------------------------------------------------------------- forecast

def test_forecast_gives_three_labelled_months_with_a_band():
    cfg, series, an, _ = _an("revenue")
    f = forecast.next_months(series, an, cfg["unit"])
    assert f["periods"] == ["2026-08", "2026-09", "2026-10"]
    assert all(lo < p < hi for lo, p, hi in zip(f["lo"], f["pred"], f["hi"]))
    assert 0.0 <= f["r2"] <= 1.0 and "R²" in f["caveat"]
    assert f["scenarios"]["if_persists"] == round(an["current"], 4)
    line = forecast.summary_line(f, economics.fmt_value)
    assert "2026-08" in line and "90% interval" in line


def test_sparse_history_has_no_forecast():
    cfg, series, an, _ = _an("home_decor_revenue")
    assert an["sparse"] and forecast.next_months(series, an, cfg["unit"]) is None
