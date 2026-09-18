"""Telemetry is a process-global shared by every browser session."""
import telemetry


def test_records_are_bounded_and_bookmarks_survive_trimming():
    """mark()/slice_from() hand out positional bookmarks that
    pyramid.investigate relies on, so trimming the front has to be
    compensated or a long session silently returns the wrong slice."""
    original_max, original = telemetry.MAX_RECORDS, list(telemetry.RECORDS)
    try:
        telemetry.MAX_RECORDS = 10
        for i in range(25):
            telemetry.record(f"t{i}", "claude-haiku-4-5", 1.0, 10, 10, "fixture")
        assert len(telemetry.RECORDS) <= 10

        mark = telemetry.mark()
        for i in range(3):
            telemetry.record(f"late{i}", "claude-haiku-4-5", 1.0, 10, 10, "fixture")
        assert [r["task"] for r in telemetry.slice_from(mark)] == ["late0", "late1", "late2"]
    finally:
        telemetry.MAX_RECORDS = original_max
        telemetry.RECORDS[:] = original


def test_fixture_calls_are_free():
    rec = telemetry.record("x", "claude-sonnet-5", 1.0, 1000, 1000, "fixture")
    assert rec["cost_usd"] == 0.0
    telemetry.RECORDS.pop()
