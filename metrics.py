"""Prometheus instrumentation for the engine itself.

Deliberately NOT business KPIs (those are analytical, not operational) — this
exposes how the *engine* is behaving in production: investigations run, which
detectors fire, gate outcomes, query and LLM latency, tokens and cost.

Everything degrades to a no-op if prometheus_client isn't installed, so the app
runs identically with or without the observability stack.

Scrape endpoint: http://localhost:9108/metrics  (set RATIONALE_METRICS_PORT to change)
"""
import os
import threading

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
    ENABLED = True
except Exception:                                    # library not installed
    ENABLED = False

_started = threading.Event()


class _Noop:
    def labels(self, *a, **k):
        return self

    def inc(self, *a, **k):
        pass

    def observe(self, *a, **k):
        pass

    def set(self, *a, **k):
        pass


if ENABLED:
    INVESTIGATIONS = Counter("rationale_investigations_total",
                             "Investigations completed", ["kpi", "outcome", "role"])
    INV_SECONDS = Histogram("rationale_investigation_duration_seconds",
                            "End-to-end investigation wall time",
                            buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 40, 60))
    CONFIDENCE = Histogram("rationale_confidence_score",
                           "Confidence score at the gates",
                           buckets=(0.2, 0.35, 0.5, 0.6, 0.7, 0.75, 0.85, 0.95, 1.0))
    DETECTOR = Counter("rationale_detector_flags_total",
                       "Detector votes", ["detector", "flag"])
    GATES = Counter("rationale_gate_outcomes_total", "Gate outcomes", ["gate", "result"])
    LLM_CALLS = Counter("rationale_llm_calls_total", "LLM calls", ["model", "mode", "task"])
    LLM_TOKENS = Counter("rationale_llm_tokens_total", "LLM tokens",
                         ["model", "direction"])
    LLM_COST = Counter("rationale_llm_cost_usd_total", "Estimated LLM spend (USD)", ["model"])
    LLM_SECONDS = Histogram("rationale_llm_latency_seconds", "LLM call latency", ["model"],
                            buckets=(0.05, 0.25, 1, 2.5, 5, 10, 20, 40))
    OPS = Counter("rationale_engine_operations_total",
                  "Deterministic work performed", ["kind"])   # sql / stats / ml / retrieval
    KPIS_FLAGGED = Gauge("rationale_kpis_flagged", "KPIs outside their normal range",
                         ["period", "role"])
    KPIS_SCANNED = Gauge("rationale_kpis_scanned", "KPIs scanned", ["period", "role"])
else:
    INVESTIGATIONS = INV_SECONDS = CONFIDENCE = DETECTOR = GATES = _Noop()
    LLM_CALLS = LLM_TOKENS = LLM_COST = LLM_SECONDS = OPS = _Noop()
    KPIS_FLAGGED = KPIS_SCANNED = _Noop()


def serve():
    """Start the /metrics endpoint once per process (safe to call repeatedly)."""
    if not ENABLED or _started.is_set():
        return False
    # opt-in: the Grafana/Prometheus layer is parked — set RATIONALE_METRICS=1
    # (and `cd ops && docker compose up -d`) to re-enable the full stack
    if os.environ.get("RATIONALE_METRICS", "0") != "1":
        return False
    # hosted platforms often forbid binding extra ports — never let that break the app
    try:
        start_http_server(int(os.environ.get("RATIONALE_METRICS_PORT", "9108")))
        _started.set()
        return True
    except OSError:          # port already bound (Streamlit hot-reload) — fine
        _started.set()
        return True
    except BaseException:
        return False


def record_investigation(result: dict):
    """Called once per completed investigation."""
    if not ENABLED:
        return
    INVESTIGATIONS.labels(result.get("kpi", "?"), result.get("outcome", "?"),
                          result.get("role", "?")).inc()
    INV_SECONDS.observe(result.get("wall_ms", 0) / 1000.0)
    conf = result.get("confidence") or {}
    if conf.get("value") is not None:
        CONFIDENCE.observe(float(conf["value"]))
        GATES.labels("evidence", "pass" if conf.get("evidence_gate") else "fail").inc()
        GATES.labels("action", "pass" if conf.get("action_gate") else "fail").inc()
    for v in result.get("detector_ensemble", []):
        DETECTOR.labels(v["detector"].split(" (")[0][:40],
                        "flag" if v["flag"] else "clear").inc()
    mix = result.get("method_mix") or {}
    for kind, key in (("sql", "sql_queries"), ("stats", "stat_tests"),
                      ("ml", "ml_models"), ("retrieval", "docs_retrieved")):
        if mix.get(key):
            OPS.labels(kind).inc(mix[key])


def record_llm(task: str, model: str, mode: str, latency_ms: float,
               in_tok: int, out_tok: int, cost_usd: float):
    """Called from telemetry.record for every LLM call."""
    if not ENABLED:
        return
    LLM_CALLS.labels(model, mode, task.split("_")[0]).inc()
    LLM_TOKENS.labels(model, "input").inc(in_tok)
    LLM_TOKENS.labels(model, "output").inc(out_tok)
    LLM_COST.labels(model).inc(cost_usd)
    LLM_SECONDS.labels(model).observe(latency_ms / 1000.0)


def record_scan(period: str, role: str, scanned: int, flagged: int):
    if ENABLED:
        KPIS_SCANNED.labels(period, role).set(scanned)
        KPIS_FLAGGED.labels(period, role).set(flagged)
