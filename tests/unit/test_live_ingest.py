"""The live ingestion lane.

It is a demo artifact, but it makes a factual claim on stage -- "this data did
not exist when the page loaded" -- so it gets tested like anything else.
"""
import pytest

from ops import ingest
from services import live_ingest


@pytest.fixture(autouse=True)
def clean_lane():
    ingest.reset()
    yield
    ingest.reset()


def test_absent_lane_reports_nothing_rather_than_crashing():
    assert live_ingest.status() == {}
    v = live_ingest.verdict()
    assert v["total"] == 0 and v["assessable"] is False


def test_writer_produces_readable_events():
    ingest.ensure_lane()
    import random
    rng = random.Random(1)
    rows = [ingest.emit(rng, degraded=False) for _ in range(5)]
    assert all(set(r) == set(ingest.FIELDS) for r in rows)
    assert all(r["sla_breaches"] <= r["shipments"] for r in rows)


def test_verdict_refuses_to_call_it_on_too_few_events(tmp_path, monkeypatch):
    """Same discipline as the sparse-history guard: say 'not enough yet'
    rather than render a confident number off three rows."""
    import csv
    ingest.ensure_lane()
    with open(ingest.EVENTS, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ingest.FIELDS)
        import random
        rng = random.Random(2)
        for _ in range(3):
            w.writerow(ingest.emit(rng, degraded=False))
    v = live_ingest.verdict()
    assert v["total"] == 3
    assert v["assessable"] is False
    assert "events needed" in v["note"]


def test_injected_degradation_is_detected_in_the_right_region():
    """The whole point of the lane: a real detector firing on data written by
    another process."""
    import csv
    import random
    ingest.ensure_lane()
    rng = random.Random(3)
    with open(ingest.EVENTS, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ingest.FIELDS)
        for i in range(80):
            w.writerow(ingest.emit(rng, degraded=i >= 30))
    v = live_ingest.verdict()
    assert v["assessable"] is True
    assert v["breached"] == ["North-West"], v["breached"]


def test_healthy_traffic_does_not_breach():
    import csv
    import random
    ingest.ensure_lane()
    rng = random.Random(4)
    with open(ingest.EVENTS, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ingest.FIELDS)
        for _ in range(80):
            w.writerow(ingest.emit(rng, degraded=False))
    v = live_ingest.verdict()
    assert v["assessable"] is True
    assert v["breached"] == []


def test_lane_is_isolated_from_the_demo_tables():
    """Mutating sales_orders mid-demo would move the recorded numbers and
    invalidate the fixtures, so the lane must stay separate."""
    assert "live" in str(ingest.EVENTS).replace("\\", "/").split("/")[-2]
    from engine import db
    assert "live" not in db._SOURCES
