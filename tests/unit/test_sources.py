"""Heterogeneous sources, reconciled at ingestion (requirement 2 of the brief).

Three systems in three formats land in one governed namespace, and the engine
says where each came from and whether it was live. The live PostgreSQL path is
exercised for real when RATIONALE_TEST_PG is set (always in CI)."""
import os

import duckdb
import pytest

from engine import db, sources

BASE = db.BASE
PG = os.environ.get("RATIONALE_TEST_PG")


def _contract():
    return db.load_contract()


def test_the_contract_declares_three_systems_in_three_formats():
    reg = sources.registry(_contract(), BASE)
    assert set(reg) == {"sales_orders", "ops_fulfilment", "crm_events", "marketing_weekly"}
    kinds = {s["kind"] for s in reg.values()}
    assert kinds == {"postgres", "csv", "jsonl"}
    systems = {s["system"] for s in reg.values()}
    assert len(systems) == 3


def test_every_source_loads_into_one_namespace_with_a_date_column(monkeypatch):
    monkeypatch.delenv("RATIONALE_OMS_DSN", raising=False)
    conn = duckdb.connect()
    prov = sources.load_all(conn, _contract(), db.DATE_COLS, BASE)
    assert [p["table"] for p in prov] == list(db.DATE_COLS)
    for p in prov:
        col = db.DATE_COLS[p["table"]]
        typ = conn.execute(f"SELECT typeof({col}) FROM {p['table']} LIMIT 1").fetchone()[0]
        assert typ == "DATE", (p["table"], typ)
        assert p["rows"] > 0 and p["as_of"]


def test_the_crm_feed_is_json_lines_and_loads_the_same_events():
    conn = duckdb.connect()
    prov = {p["table"]: p for p in sources.load_all(conn, _contract(), db.DATE_COLS, BASE, allow_live=False)}
    assert prov["crm_events"]["kind"] == "jsonl"
    assert prov["crm_events"]["rows"] == 1156           # the export the generator produced
    kinds = {r[0] for r in conn.execute("SELECT DISTINCT event_type FROM crm_events").fetchall()}
    assert {"complaint", "churn"} <= kinds
    # empty fields in the export are NULL, as they were in the flat file
    assert conn.execute("SELECT COUNT(*) FROM crm_events WHERE account_name IS NULL").fetchone()[0] > 0


def test_unconfigured_live_source_falls_back_to_the_extract_and_says_so(monkeypatch):
    monkeypatch.delenv("RATIONALE_OMS_DSN", raising=False)
    conn = duckdb.connect()
    prov = {p["table"]: p for p in sources.load_all(conn, _contract(), db.DATE_COLS, BASE)}
    oms = prov["sales_orders"]
    assert oms["kind"] == "postgres" and oms["status"] == "extract"
    assert "not configured" in oms["note"]
    assert oms["rows"] == 85222


def test_unreachable_live_source_falls_back_visibly_not_silently(monkeypatch):
    monkeypatch.setenv("RATIONALE_OMS_DSN", "postgresql://nobody:x@127.0.0.1:1/nowhere")
    monkeypatch.setattr(sources, "LIVE_TIMEOUT_S", 1)
    conn = duckdb.connect()
    prov = {p["table"]: p for p in sources.load_all(conn, _contract(), db.DATE_COLS, BASE)}
    oms = prov["sales_orders"]
    assert oms["status"] == "extract" and "unavailable" in oms["note"]
    assert oms["rows"] == 85222
    assert ":x@" not in oms["location"], "credentials must never appear in provenance"


def test_summary_counts_systems_kinds_and_statuses(monkeypatch):
    monkeypatch.delenv("RATIONALE_OMS_DSN", raising=False)
    conn = duckdb.connect()
    s = sources.summary(sources.load_all(conn, _contract(), db.DATE_COLS, BASE))
    assert s["systems"] == 3 and s["kinds"] == ["csv", "jsonl", "postgres"]
    assert s["extract"] == 1 and s["file"] == 3 and s["live"] == 0


def test_engine_reports_provenance_for_every_source():
    prov = db.source_provenance()
    assert {p["table"] for p in prov} == set(db.DATE_COLS)
    assert all(p["status"] in ("live", "extract", "file", "warehouse") for p in prov)


@pytest.mark.skipif(not PG, reason="set RATIONALE_TEST_PG to exercise the live OMS path")
def test_live_oms_is_fetched_over_the_wire_and_matches_the_extract(monkeypatch):
    """With the OMS reachable, sales_orders is pulled live from PostgreSQL and
    the row count equals the extract's: the two are the same nightly data."""
    monkeypatch.setenv("RATIONALE_OMS_DSN", PG)
    conn = duckdb.connect()
    prov = {p["table"]: p for p in sources.load_all(conn, _contract(), db.DATE_COLS, BASE)}
    oms = prov["sales_orders"]
    assert oms["status"] == "live", oms
    assert oms["fetched_at"] and "ms" in oms["note"]
    assert oms["rows"] == 85222
    creds = PG.split("://", 1)[1].split("@")[0]
    if ":" in creds:                                   # a password was supplied ...
        assert ":***@" in oms["location"]              # ... and must be redacted
    assert creds.split(":")[0] in oms["location"]       # the user may be shown
