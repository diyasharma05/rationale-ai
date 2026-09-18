"""Rendered-text snapshots, one per page per role.

This is the safety net for the modularity refactor: moving code between
modules must not change a single character a user sees. Volatile values
(timings, timestamps, generated ids) are normalised out, so a diff means a
real behavioural change.

Re-record deliberately with:  RECORD_SNAPSHOTS=1 python -m pytest tests/ui/test_snapshots.py
"""
import os
import pathlib
import re

import pytest

from tests.conftest import all_text, app_test

SNAP_DIR = pathlib.Path(__file__).parent / "__snapshots__"
PAGES = ["Dashboard", "Data", "Investigation", "Lineage", "Decision Ledger",
         "Under the Hood"]
ROLES = ["analyst", "ceo", "sales_head_north"]

# Anything that legitimately changes run to run.
_VOLATILE = [
    (re.compile(r"\d+(\.\d+)?\s*ms"), "<MS>"),
    (re.compile(r"\d+(\.\d+)?\s*s\b"), "<S>"),
    (re.compile(r"INV-[A-Z0-9-]+"), "<INV>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?"), "<TS>"),
    (re.compile(r"\$\d+\.\d+"), "<USD>"),
    (re.compile(r"\u20b9\d[\d,]*\.\d+\b"), "<INR>"),
    (re.compile(r"\s+"), " "),
]


def normalise(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)          # strip inline HTML
    for pattern, repl in _VOLATILE:
        text = pattern.sub(repl, text)
    return text.strip()


@pytest.fixture(autouse=True)
def isolated_shared_state():
    """Reset the process-wide state the app reads, so a snapshot does not
    depend on which tests ran before it. telemetry.RECORDS is a module global
    and the decision ledger is a file -- both are shared, and both are
    rendered on the pages being snapshotted.
    """
    import feedback
    import telemetry
    telemetry.reset()
    feedback.reset_ledger()
    # the live ingestion lane is written by a separate process; clear it so a
    # snapshot does not depend on whether someone left the writer running
    from ops import ingest
    ingest.reset()
    yield


def render(page: str, role: str) -> str:
    at = app_test()
    at.run()
    at.selectbox(key="role_sel").set_value(role).run()
    at.radio(key="nav").set_value(page).run()
    assert not at.exception, f"{page}/{role}: {at.exception}"
    return normalise(all_text(at))


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("page", PAGES)
def test_page_render_is_unchanged(page, role):
    path = SNAP_DIR / f"{page.replace(' ', '_').lower()}__{role}.txt"
    actual = render(page, role)
    if os.environ.get("RECORD_SNAPSHOTS") == "1" or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
        pytest.skip(f"recorded snapshot {path.name}")
    expected = path.read_text(encoding="utf-8")
    assert actual == expected, (
        f"{page}/{role} render changed.\n"
        f"If this is intentional, re-record with RECORD_SNAPSHOTS=1 and review the diff."
    )
