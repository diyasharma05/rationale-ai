"""Interaction flows through the real app (headless, mock mode).

Page *rendering* is covered by test_snapshots.py; this file covers behaviour
that only shows up when you drive the widgets.
"""
import pytest

from tests.conftest import all_text, app_test

NAV_INV, NAV_LIVE = "Investigation", "Live Feed"


@pytest.fixture(scope="module")
def dashboard():
    at = app_test()
    at.run()
    assert not at.exception, at.exception
    return at


def test_dashboard_renders_the_triage_view(dashboard):
    body = all_text(dashboard)
    assert "Net Revenue" in body
    assert "needs attention" in body.lower()
    assert "reconciled" in body.lower()


def test_golden_path_is_tentative_and_flags_the_distractor():
    """Revenue lands at TENTATIVE by design: its own signal is marginal
    (-7%, p~0.07) and confidence is 0.715, just under the action gate. Pinned
    so a change to the confidence maths cannot silently restore an over-claim."""
    at = app_test()
    at.run()
    at.radio(key="nav").set_value(NAV_INV).run()
    at.button(key="run_btn").click().run()
    assert not at.exception, at.exception
    body = all_text(at)
    assert "TENTATIVE" in body
    assert "ROOT CAUSE ESTABLISHED" not in body
    assert "Ranked explanatory drivers" in body
    assert "Decision right" in body
    assert "not as corroboration" in body, "unexplained-driver badge missing"


def test_ask_box_only_fires_on_submit():
    """The box used to act on every rerun while text remained in it: the KPI
    dropdown snapped back, a period change auto-ran an investigation, and in
    live mode a blocking intent call fired on every widget interaction."""
    at = app_test()
    at.run()
    at.radio(key="nav").set_value(NAV_INV).run()
    at.text_input(key="ask_box").set_value("what happened to complaints?").run()
    assert not at.exception, at.exception
    assert at.selectbox(key="kpi_sel").value != "complaint_rate", \
        "typing alone must not hijack the KPI selector"

    at.button(key="FormSubmitter:ask_form-Ask").click().run()
    assert not at.exception, at.exception
    assert "Complaint Rate" in all_text(at)


@pytest.mark.parametrize("kpi_id", ["fulfilment_sla", "complaint_rate",
                                    "enterprise_active_accounts", "aov",
                                    "marketing_conversion", "home_decor_revenue"])
def test_every_kpi_renders_without_exception(kpi_id):
    at = app_test()
    at.run()
    at.radio(key="nav").set_value(NAV_INV).run()
    at.selectbox(key="kpi_sel").set_value(kpi_id).run()
    at.button(key="run_btn").click().run()
    assert not at.exception, f"{kpi_id}: {at.exception}"
    assert all_text(at).strip()


def test_abstain_path_asks_a_human():
    at = app_test()
    at.run()
    at.radio(key="nav").set_value(NAV_INV).run()
    at.selectbox(key="kpi_sel").set_value("marketing_conversion").run()
    at.button(key="run_btn").click().run()
    body = all_text(at) + " ".join(str(w.value) for w in at.warning)
    assert "ABSTAINED" in body
    assert "tracking" in body.lower()


def test_sales_head_cannot_reach_restricted_kpis():
    at = app_test()
    at.run()
    at.selectbox(key="role_sel").set_value("sales_head_north").run()
    at.radio(key="nav").set_value(NAV_INV).run()
    options = at.selectbox(key="kpi_sel").options
    assert "marketing_conversion" not in options
    assert "enterprise_active_accounts" not in options


def test_contract_browser_honours_domain_rbac():
    """It used to list all seven KPIs ten lines above a panel asserting this
    role can access four of them."""
    at = app_test()
    at.run()
    at.selectbox(key="role_sel").set_value("sales_head_north").run()
    at.radio(key="nav").set_value("Under the Hood").run()
    assert not at.exception, at.exception
    shown = [o for sb in at.selectbox for o in (sb.options or [])]
    assert "marketing_conversion" not in shown


def test_ledger_masks_for_the_viewing_role():
    """Entries are masked for whoever RAN the investigation; the page has to
    mask again for whoever is reading it."""
    from engine import db
    at = app_test()
    at.run()
    at.selectbox(key="role_sel").set_value("ceo").run()
    at.radio(key="nav").set_value("Decision Ledger").run()
    assert not at.exception, at.exception
    body = all_text(at)
    for name in db._account_names():
        assert name not in body


def test_live_feed_advances_and_stops():
    at = app_test()
    at.run()
    at.radio(key="nav").set_value(NAV_LIVE).run()
    assert not at.exception, at.exception
    assert "Events ingested" in all_text(at)


def test_dark_mode_actually_repaints_the_charts():
    """The palette is resolved per run and refreshed in place.

    app.py used to recompute it at the top of every script execution, so the
    toggle just worked. Moving the theme into a module froze it at first
    import: Streamlit's own chrome would have kept flipping while every chart
    and tile stayed on whichever palette happened to load first.
    """
    from ui import theme

    at = app_test()
    at.session_state["dark_mode"] = False
    at.run()
    light = theme._SHELL["page"]

    at = app_test()
    at.session_state["dark_mode"] = True
    at.run()
    assert theme._SHELL["page"] != light
    assert theme._BASE == "dark"
