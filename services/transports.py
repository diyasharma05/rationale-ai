"""How an approved message actually leaves the building.

Two transports behind one interface, the same pattern the LLM client uses:
a deterministic offline default, and a real one that is opt-in. The demo runs
on the default and shows the entire flow without touching a network.
"""
import json
import os
import pathlib
import time

STATE = pathlib.Path(os.environ.get("RATIONALE_STATE")
                     or pathlib.Path(__file__).resolve().parent.parent / "data" / "state")
SENT_LOG = STATE / "dispatched.jsonl"


class DryRunTransport:
    """Records the send instead of performing it.

    This is the default, and not only for demo safety: an engine that can
    message real people is a different risk class from one that renders a
    page, so delivery should be something you switch on deliberately.
    """

    name = "dry-run"
    live = False

    def send(self, message: dict) -> dict:
        STATE.mkdir(parents=True, exist_ok=True)
        record = {"ts": time.time(), "transport": self.name, **message}
        with open(SENT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
        return {"ok": True, "transport": self.name,
                "detail": f"recorded to {SENT_LOG.name} (not delivered)"}


class MCPTransport:
    """Deliver through an MCP server (Slack, email, Jira, ServiceNow...).

    MCP is the wire, not the decision-maker: by the time a message reaches
    this class, the contract has already chosen the recipient and a human has
    already approved it. The advantage is uniformity — one interface for
    whatever the client already runs — rather than anything intelligent.

    Configure with:
        RATIONALE_MCP_COMMAND   e.g. "npx -y @modelcontextprotocol/server-slack"
        RATIONALE_MCP_TOOL      tool to call, default "send_message"
        RATIONALE_MCP_CHANNEL   destination handle passed to the tool

    NOTE: this adapter is written against the MCP python SDK but has not been
    exercised against a live server in this repo — there is no MCP server
    configured here to test against. Treat it as the integration point, and
    verify it against a real server before relying on it in front of anyone.
    """

    name = "mcp"
    live = True

    def __init__(self, command: str = None, tool: str = None, channel: str = None):
        self.command = command or os.environ.get("RATIONALE_MCP_COMMAND", "")
        self.tool = tool or os.environ.get("RATIONALE_MCP_TOOL", "send_message")
        self.channel = channel or os.environ.get("RATIONALE_MCP_CHANNEL", "")

    def available(self) -> bool:
        try:
            import mcp  # noqa: F401
        except ImportError:
            return False
        return bool(self.command)

    def send(self, message: dict) -> dict:
        if not self.available():
            return {"ok": False, "transport": self.name,
                    "detail": "no MCP server configured (set RATIONALE_MCP_COMMAND)"}
        try:
            return self._send_sync(message)
        except Exception as e:      # a failed send must never break the app
            return {"ok": False, "transport": self.name, "detail": f"{type(e).__name__}: {e}"}

    def _send_sync(self, message: dict) -> dict:
        import asyncio
        return asyncio.run(self._send(message))

    async def _send(self, message: dict) -> dict:
        import shlex

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        parts = shlex.split(self.command)
        params = StdioServerParameters(command=parts[0], args=parts[1:])
        text = f"*{message['subject']}*\n\n{message['body']}"
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(self.tool, {
                    "channel": self.channel or message.get("to", ""),
                    "text": text,
                })
        return {"ok": not getattr(result, "isError", False),
                "transport": self.name, "detail": str(getattr(result, "content", ""))[:200]}


def get_transport():
    """DryRun unless a live transport is explicitly configured."""
    if os.environ.get("RATIONALE_DISPATCH") == "mcp":
        return MCPTransport()
    return DryRunTransport()
