"""Rationale.AI as a service.

The whole point of this file is that it is short. `pyramid.investigate(kpi,
period, role)` is already a pure function of its inputs given the data, so
exposing it needs no rearchitecting -- which is the claim the deployment story
rests on: Streamlit is a client of the engine, not the system.

Run:  uvicorn api.main:app --port 8000
Docs: http://localhost:8000/docs
"""
import os
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import feedback
import store
import telemetry
from engine import db, pyramid, screening
from llm.client import LLMClient

app = FastAPI(
    title="Rationale.AI",
    version="1.0",
    summary="KPI intelligence-to-action engine: deterministic analysis, LLM for words only.",
)

_llm = LLMClient()
feedback.ensure_state()


class Investigation(BaseModel):
    kpi_id: str = Field(..., examples=["revenue"])
    period: str = Field(..., examples=["2026-07"], pattern=r"^\d{4}-\d{2}$")
    role_id: str = Field(..., examples=["analyst"])


@app.get("/healthz")
def healthz():
    """Liveness + what this instance is actually configured to do."""
    return {"status": "ok", "llm_mode": _llm.mode,
            "db": db.backend_info(), "store": store.backend_info(),
            "kpis": len(db.load_contract()["kpis"]),
            "roles": sorted(db.load_roles())}


@app.get("/kpis")
def kpis(role_id: str):
    """Domain-level RBAC: the contract decides what a role may even ask about."""
    _require_role(role_id)
    return {kpi_id: {"name": cfg["name"], "unit": cfg["unit"],
                     "owner": cfg.get("owner"), "drivers":
                     [d.get("kpi") or d.get("metric") for d in cfg.get("drivers", [])]}
            for kpi_id, cfg in db.allowed_kpis(role_id).items()}


@app.get("/scan")
def scan(role_id: str, period: str):
    """The portfolio sweep, with multiplicity control applied across it."""
    _require_role(role_id)
    fam = screening.family_qvalues(role_id, period)
    out = []
    for kpi_id, cfg in db.allowed_kpis(role_id).items():
        from engine import anomaly
        an = anomaly.analyze(db.kpi_series(kpi_id, role_id), period,
                             cfg["materiality"], cfg.get("min_history", 6))
        an = screening.screen(an, kpi_id, role_id, period)
        out.append({"kpi_id": kpi_id, "name": cfg["name"], "material": an["material"],
                    "z": an["z"], "p_value": an["p_value"],
                    "q_value": an.get("q_value"), "sparse": an["sparse"]})
    return {"period": period, "role_id": role_id, "family_size": len(fam),
            "fdr_q": screening.FDR_Q, "kpis": out}


@app.post("/investigate")
def investigate(req: Investigation):
    """Run the reasoning pyramid. Stateless given (kpi, period, role), which is
    why this scales horizontally: add replicas behind a load balancer."""
    _require_role(req.role_id)
    if req.kpi_id not in db.allowed_kpis(req.role_id):
        # Domain RBAC is enforced here, not only in the UI.
        raise HTTPException(403, f"role {req.role_id} may not access {req.kpi_id}")
    t0 = time.perf_counter()
    try:
        r = pyramid.investigate(req.kpi_id, req.period, req.role_id, _llm)
    except Exception as e:
        raise HTTPException(500, f"investigation failed: {e}")
    return {
        "kpi_id": r["kpi"], "period": r["period"], "role_id": r["role"],
        "outcome": r["outcome"],
        "confidence": r["confidence"],
        "headline": r["narrative"]["headline"],
        "body": r["narrative"]["body"],
        "actions": r["narrative"].get("actions", []),
        "hypotheses": [{k: h.get(k) for k in
                        ("rank", "driver_id", "label", "strength", "unexplained", "precedent")}
                       for h in r["hypotheses"]],
        "evidence": [{"id": s["id"], "file": s["file"], "date": s["date"]}
                     for s in r.get("snippets", [])],
        "method_mix": r.get("method_mix"),
        "llm_calls": len(r.get("telemetry", [])),
        "wall_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


@app.get("/metrics/summary")
def metrics_summary():
    return telemetry.summarize(telemetry.RECORDS)


def _require_role(role_id: str):
    if role_id not in db.load_roles():
        raise HTTPException(404, f"unknown role {role_id}")
