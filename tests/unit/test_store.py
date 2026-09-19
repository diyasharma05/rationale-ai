"""The event store: one interface, two backends.

The JSONL half must keep writing exactly the files the app always wrote, so an
existing ledger keeps working. The PostgreSQL half is opt-in (RATIONALE_TEST_PG)
and is exercised for real when a server is available -- in CI, always.
"""
import os
from datetime import datetime

import pytest

import feedback
import store


@pytest.fixture
def jsonl(tmp_path):
    return store.JsonlStore(tmp_path)


def test_jsonl_files_keep_their_historical_names(jsonl, tmp_path):
    for s in store.STREAMS:
        jsonl.append(s, {"k": 1})
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "decision_ledger.jsonl", "dispatched.jsonl", "feedback.jsonl", "outbox.jsonl"]


def test_append_then_read_preserves_order_and_coerces_like_before(jsonl):
    jsonl.append("outbox", {"n": 1, "when": datetime(2026, 7, 1, 10, 0)})
    jsonl.append("outbox", {"n": 2})
    got = jsonl.read("outbox")
    assert [e["n"] for e in got] == [1, 2]
    assert got[0]["when"] == "2026-07-01 10:00:00"      # default=str, as always


def test_torn_line_is_skipped_not_fatal(jsonl, tmp_path):
    jsonl.append("decision_ledger", {"id": "A"})
    with open(tmp_path / "decision_ledger.jsonl", "a", encoding="utf-8") as f:
        f.write('{"id": "B", "trunc' + "\n")
    jsonl.append("decision_ledger", {"id": "C"})
    assert [e["id"] for e in jsonl.read("decision_ledger")] == ["A", "C"]


def test_reset_with_seed_and_without(jsonl):
    jsonl.append("feedback", {"x": 1})
    jsonl.reset("feedback")
    assert jsonl.read("feedback") == [] and not jsonl.exists("feedback")
    jsonl.reset("decision_ledger", [{"id": "seed"}])
    assert jsonl.read("decision_ledger") == [{"id": "seed"}]


def test_feedback_module_routes_through_the_store(tmp_path):
    store.reconfigure(store.JsonlStore(tmp_path))
    try:
        feedback.reset_ledger()
        assert [e["id"] for e in feedback.read_ledger()] == ["INV-2025-11-EAST"]
        feedback.log_feedback("INV-2025-11-EAST", "down", "wrong", kpi="fulfilment_sla",
                              period="2025-11", driver="x")
        assert feedback.read_ledger()[0]["feedback"] == "down"
        assert (tmp_path / "feedback.jsonl").exists()
        assert (tmp_path / "decision_ledger.jsonl").exists()
    finally:
        store.reconfigure(None)


def test_ensure_state_appends_the_seed_without_needing_delete(tmp_path):
    """A role that may only INSERT must still be able to seed an empty ledger."""
    class InsertOnly(store.JsonlStore):
        def reset(self, *a, **k):
            raise PermissionError("no")
    store.reconfigure(InsertOnly(tmp_path))
    try:
        feedback.ensure_state()
        assert [e["id"] for e in feedback.read_ledger()] == ["INV-2025-11-EAST"]
        feedback.ensure_state()                      # idempotent
        assert len(feedback.read_ledger()) == 1
    finally:
        store.reconfigure(None)


def test_redact_hides_the_password():
    assert store.redact("postgresql://u:secret@h:5/d") == "postgresql://u:***@h:5/d"
    assert store.redact("postgresql://u@h/d") == "postgresql://u@h/d"


def test_default_store_is_jsonl_under_rationale_state():
    store.reconfigure(None)
    info = store.backend_info()
    assert info["backend"] == "jsonl"
    assert os.environ["RATIONALE_STATE"] in info["detail"]


# ---------------------------------------------------------------- PostgreSQL

PG = os.environ.get("RATIONALE_TEST_PG")
pg = pytest.mark.skipif(not PG, reason="set RATIONALE_TEST_PG=postgresql://... to run")
STREAM = "test_stream_unit"


@pytest.fixture
def pgstore():
    s = store.PostgresStore(PG)
    s.ensure_schema()
    s.reset(STREAM)
    yield s
    s.reset(STREAM)


@pg
def test_pg_roundtrip_keeps_order_and_structure(pgstore):
    pgstore.append(STREAM, {"n": 1, "when": datetime(2026, 7, 1, 10, 0), "nested": {"a": [1, 2]}})
    pgstore.append(STREAM, {"n": 2})
    got = pgstore.read(STREAM)
    assert [e["n"] for e in got] == [1, 2]
    assert got[0]["when"] == "2026-07-01 10:00:00"      # same coercion as the JSONL writer
    assert got[0]["nested"] == {"a": [1, 2]}
    assert pgstore.exists(STREAM)


@pg
def test_pg_reset_reseeds(pgstore):
    pgstore.append(STREAM, {"n": 1})
    pgstore.reset(STREAM, [{"id": "seed"}])
    assert pgstore.read(STREAM) == [{"id": "seed"}]


@pg
def test_pg_streams_are_isolated(pgstore):
    pgstore.append(STREAM, {"n": 1})
    assert pgstore.read(STREAM + "_other") == []
    assert not pgstore.exists(STREAM + "_other")
