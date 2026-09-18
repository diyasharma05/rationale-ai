"""Role-based access control. These are security properties, not features."""
import pytest

from engine import db, retrieve

RESTRICTED_FOR_SALES_HEAD = {"marketing_conversion", "enterprise_active_accounts"}


def test_row_security_is_in_the_sql_not_the_ui():
    where = db.role_where("sales_head_north")
    assert "region IN" in where
    assert db.role_where("analyst") == "", "analyst is unrestricted"
    for kpi_id in db.allowed_kpis("sales_head_north"):
        assert "region IN" in db.kpi_sql(kpi_id, "sales_head_north")


def test_restricted_role_sees_strictly_less_revenue():
    a = db.kpi_series("revenue", "analyst")
    s = db.kpi_series("revenue", "sales_head_north")
    july_a = float(a[a["period"] == "2026-07"]["value"].iloc[0])
    july_s = float(s[s["period"] == "2026-07"]["value"].iloc[0])
    assert july_s < july_a


def test_domain_security_hides_restricted_kpis():
    allowed = set(db.allowed_kpis("sales_head_north"))
    assert not (allowed & RESTRICTED_FOR_SALES_HEAD)
    assert RESTRICTED_FOR_SALES_HEAD <= set(db.allowed_kpis("analyst"))


def test_account_masking_applies_to_the_executive():
    names = db._account_names()
    assert names, "expected enterprise account names in the fixture data"
    sample = f"Call with {names[0]} about renewal"
    assert names[0] not in db.mask_text(sample, "ceo")
    assert "ACCT-" in db.mask_text(sample, "ceo")
    assert names[0] in db.mask_text(sample, "analyst")


def test_masking_reaches_retrieved_evidence_not_just_the_screen():
    """Snippets are masked before they are rendered AND before they are put in
    the LLM prompt -- the claim is that account names never leave the
    perimeter, which is the strongest compliance answer in the pitch."""
    cfg = db.allowed_kpis("ceo")["revenue"]
    res = retrieve.search(cfg, ["North-West"], [], "ceo", exclude_period="2026-07")
    blob = " ".join(s["text"] for s in res["snippets"])
    for name in db._account_names():
        assert name not in blob


@pytest.mark.parametrize("role", ["analyst", "ceo", "sales_head_north"])
def test_every_allowed_kpi_is_queryable_by_that_role(role):
    for kpi_id in db.allowed_kpis(role):
        assert not db.kpi_series(kpi_id, role).empty or kpi_id == "home_decor_revenue"
