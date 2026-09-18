"""Runtime telemetry: every LLM call is wrapped and recorded — latency, model,
input/output tokens (from response.usage), and estimated cost. Non-LLM engine
steps record latency only. Summaries surface per investigation and cumulative.
"""
import time

# $ per 1M tokens (input, output) — Anthropic list prices
PRICING = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
}
USD_INR = 88.0

RECORDS = []

# RECORDS is process-global and shared by every browser session, so it needs a
# ceiling or a long-lived deploy leaks memory. mark()/slice_from() hand out
# positional bookmarks that pyramid.investigate relies on, so trimming the
# front has to be compensated: _DROPPED counts everything evicted, and the
# bookmarks are expressed in absolute terms that survive the trim.
MAX_RECORDS = 5000
_DROPPED = 0


def _trim():
    global _DROPPED
    excess = len(RECORDS) - MAX_RECORDS
    if excess > 0:
        del RECORDS[:excess]
        _DROPPED += excess


def cost_usd(model: str, in_tok: int, out_tok: int) -> float:
    pi, po = PRICING.get(model, (0.0, 0.0))
    return (in_tok * pi + out_tok * po) / 1_000_000


def record(task: str, model: str, latency_ms: float, in_tok: int, out_tok: int, mode: str):
    c = 0.0 if mode != "live" else cost_usd(model, in_tok, out_tok)
    rec = {"ts": time.time(), "task": task, "model": model, "mode": mode,
           "latency_ms": round(latency_ms, 1), "input_tokens": in_tok,
           "output_tokens": out_tok, "cost_usd": round(c, 6),
           "cost_inr": round(c * USD_INR, 4)}
    RECORDS.append(rec)
    _trim()
    try:                       # Prometheus mirror (no-op if not installed)
        import metrics
        metrics.record_llm(task, model, mode, latency_ms, in_tok, out_tok, c)
    except Exception:
        pass
    return rec


def reset():
    """Clear the log, keeping absolute positions monotonic.

    A bare RECORDS.clear() would leave _DROPPED stale, so bookmarks handed
    out before the reset would point past the end.
    """
    global _DROPPED
    _DROPPED += len(RECORDS)
    RECORDS.clear()


def mark():
    """Bookmark before an investigation; slice_from(mark) gives its calls.

    Absolute (survives trimming), not a bare list index.
    """
    return _DROPPED + len(RECORDS)


def slice_from(idx: int):
    """Records added since `idx`. Entries evicted by _trim() are simply gone;
    clamping at 0 means a very long session degrades to "fewer rows shown"
    rather than raising or silently returning the wrong slice."""
    return RECORDS[max(0, idx - _DROPPED):]


def summarize(records):
    return {
        "llm_calls": len(records),
        "total_latency_ms": round(sum(r["latency_ms"] for r in records), 1),
        "input_tokens": sum(r["input_tokens"] for r in records),
        "output_tokens": sum(r["output_tokens"] for r in records),
        "cost_usd": round(sum(r["cost_usd"] for r in records), 6),
        "cost_inr": round(sum(r["cost_inr"] for r in records), 4),
        "modes": sorted({r["mode"] for r in records}) or ["none"],
    }
