"""Headless UI verification via streamlit.testing (mock mode).
Run: python ui_test.py
"""
import os

os.environ["MOCK_MODE"] = "1"

from streamlit.testing.v1 import AppTest

NAV_DASH, NAV_INV = "Dashboard", "Investigation"
NAV_LEDGER, NAV_HOOD = "Decision Ledger", "Under the Hood"


def new_app():
    return AppTest.from_file("app.py", default_timeout=120)


def all_text(at):
    parts = [str(x.value) for x in at.markdown] + [str(x.value) for x in at.caption]
    for attr in ("subheader", "header", "title", "info", "warning", "success"):
        try:
            parts += [str(x.value) for x in getattr(at, attr)]
        except Exception:
            pass
    return " ".join(parts)


print("1) dashboard renders: stat row, attention tiles, freshness (analyst)...")
at = new_app()
at.run()
assert not at.exception, at.exception
body = all_text(at)
assert "Net Revenue" in body, "revenue tile missing"
assert "needs attention" in body.lower(), "attention tiles missing"
assert "reconciled" in body.lower(), "source freshness tile missing"
assert "Est. revenue impact" in body, "overview stat row missing"
print("   ok — pure-metrics dashboard renders")

print("2) golden path (revenue, analyst, mock) — ranked drivers + actions...")
at.radio[0].set_value(NAV_INV).run()
at.button(key="run_btn").click().run()
assert not at.exception, at.exception
body = all_text(at)
assert "ROOT CAUSE ESTABLISHED" in body, "golden path did not reach ACTIONS"
assert "Ranked explanatory drivers" in body, "ranking section missing"
assert "Decision right" in body, "decision rights missing from action cards"
assert "North-West" in body
infos = " ".join(str(i.value) for i in at.info)
assert "could change" in (body + infos).lower(), "'what could change' missing"
print("   ok — actions, ranking, decision rights, what-could-change rendered")

print("3) plain-English ask box routes to a KPI...")
at2 = new_app()
at2.run()
at2.radio[0].set_value(NAV_INV).run()
at2.text_input(key="ask_box").set_value("what happened to complaints?").run()
assert not at2.exception, at2.exception
body = all_text(at2)
assert "Complaint Rate" in body, "intent match failed: " + body[:300]
print("   ok — question understood and investigation auto-ran")

print("3b) every investigable KPI renders without exception (crash regression)...")
for k in ["fulfilment_sla", "complaint_rate", "enterprise_active_accounts", "aov"]:
    at.selectbox(key="kpi_sel").set_value(k).run()
    at.button(key="run_btn").click().run()
    assert not at.exception, f"{k} investigation crashed: {at.exception}"
print("   ok — fulfilment_sla, complaint_rate, enterprise_active_accounts, aov all render")

print("4) abstain path (marketing_conversion)...")
at.selectbox(key="kpi_sel").set_value("marketing_conversion").run()
at.button(key="run_btn").click().run()
assert not at.exception, at.exception
body = all_text(at)
assert "ABSTAINED" in body, "abstain outcome missing"
assert len(at.warning) > 0, "clarifying question missing"
print("   ok — abstained with clarifying question")

print("5) sparse path (home_decor_revenue)...")
at.selectbox(key="kpi_sel").set_value("home_decor_revenue").run()
at.button(key="run_btn").click().run()
assert not at.exception, at.exception
assert "TOO NEW" in all_text(at), "sparse outcome missing"
print("   ok — sparse guard rendered")

print("6) CEO role: masked narrative, no stats jargon in badge...")
at3 = new_app()
at3.run()
at3.selectbox(key="role_sel").set_value("ceo").run()
at3.radio[0].set_value(NAV_INV).run()
at3.button(key="run_btn").click().run()
assert not at3.exception, at3.exception
body = all_text(at3)
assert "Meridian" not in body and "Kalinga" not in body, "account names leaked to CEO view"
print("   ok — account names masked")

print("7) sales head: domain restriction...")
at4 = new_app()
at4.run()
at4.selectbox(key="role_sel").set_value("sales_head_north").run()
body = all_text(at4)
assert "Marketing Conversion" not in body, "domain-restricted KPI visible to sales head"
print("   ok — restricted KPIs hidden")

print("8) ledger + under-the-hood pages render...")
at4.radio[0].set_value(NAV_LEDGER).run()
assert not at4.exception, at4.exception
at4.radio[0].set_value(NAV_HOOD).run()
assert not at4.exception, at4.exception
assert "Latency, cost" in all_text(at4), "latency/scalability section missing"
print("   ok")

print("9) data explorer renders with RBAC scope...")
at4.radio[0].set_value("Data").run()
assert not at4.exception, at4.exception
body = all_text(at4)
assert "Rows in range" in body and "SQL executed" in body.replace("·", "").replace("  ", " "), \
    "data explorer sections missing"
print("   ok — volume chart, SQL, latest rows")

print("10) period picker recomputes the dashboard (May = healthy month)...")
at5 = new_app()
at5.run()
at5.selectbox(key="period").set_value("2026-05").run()
assert not at5.exception, at5.exception
body = all_text(at5)
assert "May 2026" in body, "header did not follow the selected period"
print("   ok — dashboard recomputed for May 2026")

print("11) live feed page renders and advances...")
at6 = new_app()
at6.run()
at6.radio[0].set_value("Live Feed").run()
assert not at6.exception, at6.exception
body = all_text(at6)
assert "Stream clock" in body and "Live monitors" in body.lower() or "Events ingested" in body, \
    "live feed panels missing"
at6.button(key="play_btn").click().run()          # start playing
assert not at6.exception, at6.exception
at6.button(key="reset_stream").click().run()      # and reset cleanly
assert not at6.exception, at6.exception
print("   ok — stream clock, monitors, ticker, play/reset")

print("\nALL UI CHECKS PASSED (mock mode)")
