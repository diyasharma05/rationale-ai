"""Question -> KPI routing."""
import pytest

from engine import db
from services import intent


@pytest.fixture(scope="module")
def kpis():
    return db.allowed_kpis("analyst")


@pytest.mark.parametrize("question,expected", [
    ("why did revenue fall in July?", "revenue"),
    ("what happened to complaints?", "complaint_rate"),
    ("why are deliveries late", "fulfilment_sla"),
    ("how is marketing doing", "marketing_conversion"),
    ("what about churn", "enterprise_active_accounts"),
])
def test_known_phrasings_route_correctly(kpis, question, expected):
    assert intent.match_kpi(question, kpis)[0] == expected


@pytest.mark.parametrize("question", [
    "is our delivery promise slipping?",     # 'delivery' tags three KPIs
    "what is going on with our margins",     # no governed KPI
    "which region is worst?",
])
def test_ambiguous_or_unmapped_questions_refuse_to_guess(kpis, question):
    """A tie must surface as 'I could not map that' rather than picking one --
    silently investigating the wrong KPI is worse than asking."""
    assert intent.match_kpi(question, kpis)[0] is None


def test_resolve_does_not_call_the_model_in_mock_mode(kpis):
    """There is no fixture for an arbitrary question, so a miss must not
    replay an unrelated cached answer."""
    class Boom:
        mode = "mock"

        def json_call(self, *a, **k):
            raise AssertionError("must not call the model in mock mode")

    assert intent.resolve("what about our margins", kpis, Boom())[0] is None
