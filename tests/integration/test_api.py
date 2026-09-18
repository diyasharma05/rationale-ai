"""The engine as a service.

These exist to keep the deployment claim honest: if the API drifts from the
UI, "Streamlit is just a client" stops being true.
"""
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from service.api import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_healthz_reports_offline_mode(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["llm_mode"] == "mock"


def test_scan_reports_multiplicity_control(client):
    body = client.get("/scan", params={"role_id": "analyst", "period": "2026-07"}).json()
    assert body["fdr_q"] == 0.10
    flagged = {k["kpi_id"] for k in body["kpis"] if k["material"]}
    assert flagged == {"revenue", "fulfilment_sla", "complaint_rate",
                       "enterprise_active_accounts", "marketing_conversion"}


def test_investigate_matches_the_engine(client):
    body = client.post("/investigate", json={
        "kpi_id": "revenue", "period": "2026-07", "role_id": "analyst"}).json()
    assert body["outcome"] == "tentative"
    assert 0.60 <= body["confidence"]["value"] < 0.75
    assert body["hypotheses"][0]["driver_id"] == "fulfilment_sla"


def test_domain_rbac_is_enforced_at_the_api_not_just_the_ui(client):
    r = client.post("/investigate", json={
        "kpi_id": "marketing_conversion", "period": "2026-07",
        "role_id": "sales_head_north"})
    assert r.status_code == 403


def test_row_rbac_holds_through_the_api(client):
    a = client.post("/investigate", json={
        "kpi_id": "revenue", "period": "2026-07", "role_id": "analyst"}).json()
    s = client.post("/investigate", json={
        "kpi_id": "revenue", "period": "2026-07", "role_id": "sales_head_north"}).json()
    assert a["confidence"] != s["confidence"] or a["body"] != s["body"]


def test_unknown_role_is_rejected(client):
    assert client.get("/kpis", params={"role_id": "nobody"}).status_code == 404


def test_bad_period_is_rejected_by_the_schema(client):
    r = client.post("/investigate", json={
        "kpi_id": "revenue", "period": "July", "role_id": "analyst"})
    assert r.status_code == 422
