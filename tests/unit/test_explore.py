"""Ad-hoc exploration: allowlisted identifiers, bound parameters, RBAC."""
import pytest

from engine import explore


def test_sources_and_grains_are_allowlisted():
    with pytest.raises(ValueError):
        explore.volume_sql("sales_orders; DROP TABLE sales_orders", "month", "analyst")
    with pytest.raises(ValueError):
        explore.volume_sql("sales_orders", "century", "analyst")


def test_date_bounds_are_bound_not_interpolated():
    """The date slider used to be f-string'd straight into the statement."""
    sql = explore.volume_sql("sales_orders", "month", "analyst")
    assert "?" in sql
    assert "2026" not in sql


def test_rbac_clause_is_present_for_restricted_roles():
    assert "region IN" in explore.volume_sql("sales_orders", "day", "sales_head_north")
    assert "region IN" not in explore.volume_sql("sales_orders", "day", "analyst")


def test_restricted_role_sees_fewer_rows():
    _, a = explore.volume("sales_orders", "month", "analyst", "2026-07-01", "2026-07-31")
    _, s = explore.volume("sales_orders", "month", "sales_head_north", "2026-07-01", "2026-07-31")
    assert int(s["rows_"].sum()) < int(a["rows_"].sum())


def test_latest_rows_respects_the_row_filter():
    _, rows = explore.latest_rows("sales_orders", "sales_head_north",
                                  "2026-07-01", "2026-07-31", limit=200)
    assert set(rows["region"].unique()) <= {"North", "North-West"}
