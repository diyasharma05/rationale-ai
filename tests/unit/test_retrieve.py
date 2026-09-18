"""Retrieval precision and the echo-chamber guard."""
import re

from engine import retrieve


def hits(term, text):
    return len(re.findall(retrieve._term_re(term), text.lower()))


def test_region_term_does_not_match_inside_another_region():
    """A plain \b is not enough here: a hyphen is a non-word character, so
    \bwest\b still matches inside "north-west". That false match is why a
    national marketing investigation retrieved the North-West enterprise
    exit-call transcript as its top evidence."""
    assert hits("west", "north-west") == 0
    assert hits("west", "the West region") == 1
    assert hits("north-west", "north-west hub") == 1


def test_terms_do_not_match_inside_longer_words():
    assert hits("west", "westbound") == 0
    assert hits("sla", "translate") == 0


def test_ledger_precedent_must_be_strictly_in_the_past():
    """Same-period entries were excluded, but FUTURE ones were not: analysing a
    month before the incident pulled the incident's own conclusions back as
    evidence and filled every slot."""
    assert retrieve._admissible_ledger({"period": "2026-05"}, "2026-07") is True
    assert retrieve._admissible_ledger({"period": "2026-07"}, "2026-07") is False
    assert retrieve._admissible_ledger({"period": "2026-08"}, "2026-07") is False


def test_feedback_mirror_rows_are_never_evidence():
    """log_feedback writes ledger rows with period "", which the old guard
    never excluded."""
    assert retrieve._admissible_ledger({"period": ""}, "2026-07") is False
    assert retrieve._admissible_ledger({}, "2026-07") is False


def test_self_authored_precedent_cannot_crowd_out_documents():
    from engine import db
    cfg = db.allowed_kpis("analyst")["revenue"]
    res = retrieve.search(cfg, ["North-West"], [], "analyst", exclude_period="2026-07")
    n_ledger = sum(1 for s in res["snippets"] if s["kind"] == "ledger")
    assert n_ledger <= retrieve.MAX_LEDGER_SNIPPETS
