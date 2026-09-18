"""Signal detection: small-sample statistics and honest wording."""
import pandas as pd

from engine import anomaly, db, pyramid


def series(values, start="2025-09"):
    p = pd.period_range(start, periods=len(values), freq="M").astype(str)
    return pd.DataFrame({"period": list(p), "value": values})


def test_reports_t_and_p_not_just_z():
    an = anomaly.analyze(series([10, 10.2, 9.8, 10.1, 9.9, 10.0, 13.0]),
                         "2026-03", {"min_abs_z": 2.0, "min_pct": 0.0})
    assert an["t"] is not None and an["p_value"] is not None
    assert 0.0 <= an["p_value"] <= 1.0


def test_prediction_se_makes_the_test_less_significant_than_z_implies():
    """|z| is computed against s; the quantity actually being tested is a NEW
    observation, whose spread is s*sqrt(1+1/n), and the reference at these
    sample sizes is a t, not a normal. Reading |z|>=2 as p=0.046 overstates
    significance -- at n=6 the honest figure is nearer p=0.12."""
    from scipy import stats
    an = anomaly.analyze(series([9, 10, 11, 9, 10, 11, 12]),
                         "2026-03", {"min_abs_z": 2.0, "min_pct": 0.0})
    assert abs(an["t"]) < abs(an["z"]), "prediction SE must shrink the statistic"
    naive_normal_p = 2 * stats.norm.sf(abs(an["z"]))
    assert an["p_value"] > naive_normal_p * 1.5, (
        f"t-based p={an['p_value']:.4f} should be materially larger than the "
        f"normal approximation p={naive_normal_p:.4f}")


def test_direction_and_magnitude_come_from_the_same_baseline():
    """Direction used to be read off sign(z) (vs the long-run mean) while the
    magnitude printed was vs the trailing 3 months, so a metric that fell 7%
    could render as 'up 7.0%'."""
    cfg = db.allowed_kpis("analyst")["complaint_rate"]
    an = anomaly.analyze(db.kpi_series("complaint_rate", "analyst"), "2026-05",
                         cfg["materiality"], 6)
    assert an["z"] > 0 and an["pct_vs_recent"] < 0, "this month is the disagreeing case"
    assert "down" in pyramid._movement_str(an, cfg["unit"], technical=False)


def test_prose_form_carries_no_statistics_vocabulary():
    """The sanitizer drops whole sentences containing 'z=', which is why the
    offline template narrative collapsed to a single clause."""
    cfg = db.allowed_kpis("analyst")["revenue"]
    an = anomaly.analyze(db.kpi_series("revenue", "analyst"), "2026-07", cfg["materiality"], 6)
    prose = pyramid._movement_str(an, cfg["unit"], technical=False)
    assert "z=" not in prose
    assert "z=" in pyramid._movement_str(an, cfg["unit"], technical=True)
    assert pyramid._clip(prose, 4, 520) == prose, "prose must survive the sanitizer intact"


def test_sparse_history_short_circuits():
    an = anomaly.analyze(series([10, 11]), "2025-10", {"min_abs_z": 2.0, "min_pct": 0.0})
    assert an["sparse"] is True
