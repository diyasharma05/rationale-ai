"""The MCP adapter, exercised against a real MCP server.

The server is a local one (tests/fixtures/echo_mcp_server.py) that speaks the
actual protocol over stdio and records what it is asked to post. A pass here
means the adapter's handshake, tool discovery, argument mapping and call are
correct -- which is where the risk was. It does not mean any particular
vendor's server accepts the payload; that needs the vendor's server and its
credentials.
"""
import json
import os
import pathlib
import sys

import pytest

from engine import db, pyramid
from services import outbox
from services.transports import MCPTransport, _map_args, _pick_tool

pytest.importorskip("mcp")

SERVER = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "echo_mcp_server.py"


@pytest.fixture
def echo_log(tmp_path, monkeypatch):
    """Point the echo server's log into tmp. Proves the env passthrough too:
    the SDK gives the child a minimal environment, so this only works if the
    adapter forwards ECHO_MCP_* explicitly."""
    log = tmp_path / "echo.log"
    monkeypatch.setenv("ECHO_MCP_LOG", str(log))
    outbox.reset()
    yield log
    outbox.reset()


def _transport(**kw):
    return MCPTransport(command=f'"{sys.executable}" "{SERVER}"', channel="C0TEST", **kw)


def test_full_flow_posts_through_a_real_mcp_server(llm, echo_log):
    """draft -> approve -> send, with the send actually crossing the MCP wire."""
    r = pyramid.investigate("fulfilment_sla", "2026-07", "analyst", llm)
    cfg = db.load_contract()["kpis"]["fulfilment_sla"]
    mid = outbox.draft(r, cfg, actor="analyst")[0]
    outbox.approve(mid, actor="ceo", note="go")

    t = _transport()
    res = outbox.send(mid, transport=t)
    assert res["ok"] is True, res
    assert res["transport"] == "mcp"

    records = [json.loads(l) for l in echo_log.read_text(encoding="utf-8").splitlines()]
    posts = [x for x in records if x["tool"] == "slack_post_message"]
    assert len(posts) == 1
    assert posts[0]["channel_id"] == "C0TEST"
    assert "Fulfilment SLA" in posts[0]["text"]
    assert "Decision right" in posts[0]["text"]
    assert "VP Operations" in posts[0]["text"] or "COO" in posts[0]["text"]

    sent = next(m for m in outbox.messages() if m["id"] == mid)
    assert sent["status"] == "sent" and sent["sent_via"] == "mcp"


def test_discovery_picks_the_posting_tool_not_the_first_tool(echo_log):
    """The echo server lists slack_list_channels first, on purpose."""
    t = _transport()
    res = t.send({"subject": "s", "body": "b", "to": "C0TEST"})
    assert res["ok"] is True, res
    assert res["tool"] == "slack_post_message"
    records = [json.loads(l) for l in echo_log.read_text(encoding="utf-8").splitlines()]
    assert all(x["tool"] == "slack_post_message" for x in records)


def test_arguments_are_mapped_from_the_servers_schema():
    """The official Slack server wants channel_id/text; another server might
    want channel/message. The adapter must read the schema, not assume."""
    class Tool:
        def __init__(self, name, props):
            self.name = name
            self.inputSchema = {"properties": {p: {} for p in props}, "required": props}

    slack = Tool("slack_post_message", ["channel_id", "text"])
    assert _map_args(slack, "C1", "hi") == {"channel_id": "C1", "text": "hi"}
    other = Tool("send_message", ["channel", "message"])
    assert _map_args(other, "C1", "hi") == {"channel": "C1", "message": "hi"}

    tools = [Tool("slack_list_channels", ["limit"]), slack]
    assert _pick_tool(tools).name == "slack_post_message"
    assert _pick_tool(tools, wanted="slack_list_channels").name == "slack_list_channels"
    assert _pick_tool([Tool("slack_get_users", [])]) is None


def test_missing_required_argument_fails_closed():
    """If a server demands something the adapter cannot supply, refuse rather
    than send a malformed call."""
    class Tool:
        name = "slack_post_message"
        inputSchema = {"properties": {"channel_id": {}, "text": {}, "thread_ts": {}},
                       "required": ["channel_id", "text", "thread_ts"]}
    args = _map_args(Tool(), "C1", "hi")
    assert "thread_ts" not in args        # the send path checks required - args


def test_unconfigured_transport_reports_not_sends(monkeypatch):
    monkeypatch.delenv("RATIONALE_MCP_COMMAND", raising=False)
    t = MCPTransport(command="")
    res = t.send({"subject": "s", "body": "b"})
    assert res["ok"] is False
    assert "RATIONALE_MCP_COMMAND" in res["detail"]


def test_server_that_cannot_start_fails_closed():
    t = MCPTransport(command=f'"{sys.executable}" -c "import sys; sys.exit(3)"')
    res = t.send({"subject": "s", "body": "b"})
    assert res["ok"] is False
    assert res["transport"] == "mcp"
