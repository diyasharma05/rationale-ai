"""A real MCP server that records what it is told to send.

This is the test double for MCPTransport. It speaks the actual protocol over
stdio -- handshake, tool listing, tool call -- so a passing test means the
adapter is talking MCP correctly, not merely that its Python runs. What it
does NOT prove is that any particular vendor's server accepts the payload;
that needs the vendor's server.

Two tools on purpose: one whose name and argument names match the official
Slack server (`slack_post_message`, `channel_id`, `text`), and a decoy, so
the adapter's tool discovery has to actually choose rather than take the
first thing it sees.

Run standalone:  python tests/fixtures/echo_mcp_server.py
Records land in the path given by ECHO_MCP_LOG.
"""
import json
import os
import time

from mcp.server.fastmcp import FastMCP

LOG = os.environ.get("ECHO_MCP_LOG", os.path.join(os.path.dirname(__file__), "echo_mcp.log"))

server = FastMCP("echo-slack")


def _record(tool: str, **payload):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "tool": tool, **payload}) + "\n")


@server.tool()
def slack_list_channels(limit: int = 100) -> str:
    """List channels (decoy: exists so discovery cannot just take tool #1)."""
    _record("slack_list_channels", limit=limit)
    return json.dumps({"channels": [{"id": "C0TEST", "name": "rationale-test"}]})


@server.tool()
def slack_post_message(channel_id: str, text: str) -> str:
    """Post a message to a channel. Same signature as the official Slack MCP server."""
    _record("slack_post_message", channel_id=channel_id, text=text)
    return json.dumps({"ok": True, "channel": channel_id, "ts": str(time.time())})


if __name__ == "__main__":
    server.run()
