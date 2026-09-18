"""Caching must never be able to defeat RBAC.

Engine caches are process-global and (in the app) shared across browser
sessions, so a cache key that omits the role is not a staleness bug -- it is a
cross-role data leak. Concurrency is exactly when this would bite, which is why
it gets its own suite rather than a comment.
"""
import inspect

import pytest

from engine import cache, db, retrieve, screening, stats_ml, stream

# Role-independent by construction: contract/role definitions and source
# freshness are the same for everyone, and account names are masked at use.
ROLE_INDEPENDENT = {"load_contract", "load_roles", "source_freshness", "_account_names",
                    "load_corpus", "benjamini_hochberg", "_term_re"}


def _cached_callables(module):
    for name, obj in vars(module).items():
        if callable(obj) and hasattr(obj, "cache_info"):
            yield name, obj


MODULES = [db, stream, retrieve, screening]


@pytest.mark.parametrize("module", MODULES)
def test_role_scoped_caches_key_on_role(module):
    for name, fn in _cached_callables(module):
        if name in ROLE_INDEPENDENT:
            continue
        params = inspect.signature(fn.__wrapped__).parameters
        assert "role_id" in params, (
            f"{module.__name__}.{name} is cached but does not take role_id; "
            "a cache hit would serve one role another role's rows")


def test_the_cache_key_rule_is_actually_exercised():
    """Guard against the check above quietly becoming vacuous: if every cached
    callable ends up on the allowlist, the suite would pass while enforcing
    nothing."""
    checked = [f"{m.__name__}.{n}" for m in MODULES
               for n, _ in _cached_callables(m) if n not in ROLE_INDEPENDENT]
    assert len(checked) >= 3, f"cache-key rule is not being enforced anywhere: {checked}"


def test_priming_as_analyst_does_not_leak_into_a_restricted_role():
    """The poisoning test: warm every cached path as the unrestricted role,
    then read as the restricted one and assert the numbers are still scoped."""
    for kpi_id in db.allowed_kpis("analyst"):
        db.kpi_series(kpi_id, "analyst")
    db.revenue_daily("analyst")
    stream.recent_events(__import__("datetime").date(2026, 7, 20), "analyst")

    july_analyst = float(db.kpi_series("revenue", "analyst").query("period == '2026-07'")["value"].iloc[0])
    july_sales = float(db.kpi_series("revenue", "sales_head_north").query("period == '2026-07'")["value"].iloc[0])
    assert july_sales < july_analyst, "restricted role served the unrestricted figure"

    allowed = set(db.allowed_kpis("sales_head_north"))
    assert "marketing_conversion" not in allowed


def test_iforest_cache_key_separates_roles():
    """The frame handed to the model is already RBAC-filtered, so two roles
    hash differently and cannot share a cached verdict."""
    a = cache.frame_fingerprint(db.revenue_daily("analyst"))
    s = cache.frame_fingerprint(db.revenue_daily("sales_head_north"))
    assert a != s

    va = stats_ml.iforest_daily(db.revenue_daily("analyst"), "2026-07")
    vs = stats_ml.iforest_daily(db.revenue_daily("sales_head_north"), "2026-07")
    assert va["n_models"] != vs["n_models"], "restricted role should fit fewer regional models"


def test_stream_ticker_is_region_scoped_under_cache():
    import datetime
    cur = datetime.date(2026, 7, 20)
    stream.recent_events(cur, "analyst")          # prime
    rows = stream.recent_events(cur, "sales_head_north")
    text = " ".join(r["text"] for r in rows)
    for region in ("South", "East"):
        assert f"({region})" not in text, f"{region} leaked into the North-only ticker"
