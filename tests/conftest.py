"""Shared test setup.

Two things have to happen before anything else imports the app:

* MOCK_MODE, so no test can make a live API call.
* RATIONALE_STATE pointed at a throwaway directory. pyramid.investigate()
  appends to the decision ledger on every call, and the ledger is part of the
  Level-2 retrieval corpus -- so without this a test run silently rewrites the
  corpus it is asserting against, and the suite stops being reproducible.

feedback.py reads RATIONALE_STATE at import time, so this must run at conftest
import, not inside a fixture.
"""
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_STATE = pathlib.Path(tempfile.gettempdir()) / "rationale_pytest_state"
_STATE.mkdir(parents=True, exist_ok=True)
os.environ["MOCK_MODE"] = "1"
os.environ["RATIONALE_STATE"] = str(_STATE)

import pytest  # noqa: E402

import feedback  # noqa: E402

PERIOD = "2026-07"
ROLES = ["analyst", "ceo", "sales_head_north"]


@pytest.fixture(scope="session", autouse=True)
def clean_ledger():
    """One seeded ledger for the whole session, restored at the end."""
    feedback.reset_ledger()
    yield
    feedback.reset_ledger()


@pytest.fixture(scope="session")
def llm():
    from llm.client import LLMClient
    client = LLMClient()
    assert client.mode == "mock", "tests must never hit the live API"
    return client


def app_test(timeout: int = 180):
    """A fresh headless app instance, theme pinned.

    The sidebar's dark-mode toggle calls st.config.set_option, which is
    process-global and would otherwise leak between AppTest runs.
    """
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=timeout)
    at.session_state["dark_mode"] = False
    return at


def all_text(at) -> str:
    parts = [str(x.value) for x in at.markdown] + [str(x.value) for x in at.caption]
    for attr in ("subheader", "header", "title", "info", "warning", "success", "error"):
        try:
            parts += [str(x.value) for x in getattr(at, attr)]
        except Exception:
            pass
    return " ".join(parts)
