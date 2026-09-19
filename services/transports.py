"""How an approved message actually leaves the building.

Two transports behind one interface, the same pattern the LLM client uses:
a deterministic offline default, and a real one that is opt-in. The demo runs
on the default and shows the entire flow without touching a network.
"""
import json
import os
import pathlib
import time

import store

SENT_STREAM = "dispatched"     # the dispatch log: JSONL by default, PostgreSQL when configured


class DryRunTransport:
    """Records the send instead of performing it.

    This is the default, and not only for demo safety: an engine that can
    message real people is a different risk class from one that renders a
    page, so delivery should be something you switch on deliberately.
    """

    name = "dry-run"
    live = False

    def send(self, message: dict) -> dict:
        record = {"ts": time.time(), "transport": self.name, **message}
        store.append(SENT_STREAM, record)
        return {"ok": True, "transport": self.name,
                "detail": "recorded to the dispatch log (not delivered)"}


# Tool discovery. Every vendor names its posting tool differently -- the
# official Slack server says slack_post_message(channel_id, text), others say
# send_message(channel, text) -- so the adapter asks the server what it has
# and maps by schema rather than hardcoding one vendor's names. The first
# version of this file hardcoded send_message/channel and would have failed
# on its first real call.
_PREFERRED_TOOLS = ("slack_post_message", "post_message", "send_message",
                    "send_email", "create_message", "post")
_CHANNEL_KEYS = ("channel_id", "channel", "chat_id", "to", "recipient", "conversation_id")
_TEXT_KEYS = ("text", "message", "content", "body", "markdown")


def _pick_tool(tools, wanted: str = ""):
    by_name = {t.name: t for t in tools}
    if wanted:
        return by_name.get(wanted)
    for name in _PREFERRED_TOOLS:
        if name in by_name:
            return by_name[name]
    for t in tools:                     # anything that looks like it posts
        n = t.name.lower()
        if ("post" in n or "send" in n) and ("message" in n or "msg" in n or "mail" in n):
            return t
    return None


def _map_args(tool, channel: str, text: str) -> dict:
    props = (getattr(tool, "inputSchema", None) or {}).get("properties", {}) or {}
    args = {}
    chan_key = next((k for k in _CHANNEL_KEYS if k in props), None)
    text_key = next((k for k in _TEXT_KEYS if k in props), None)
    if chan_key:
        args[chan_key] = channel
    if text_key:
        args[text_key] = text
    return args


class MCPTransport:
    """Deliver through an MCP server (Slack, email, Jira, ServiceNow ...).

    MCP is the wire, not the decision-maker: by the time a message reaches
    this class the contract has already chosen the recipient and a human has
    already approved it. The advantage is uniformity -- one interface for
    whatever the client already runs.

    Configure with:
        RATIONALE_MCP_COMMAND   how to start the server,
                                e.g. "npx -y @modelcontextprotocol/server-slack"
        RATIONALE_MCP_CHANNEL   destination handle (a Slack channel id, an address)
        RATIONALE_MCP_TOOL      optional: force a tool name instead of discovering one

    The server child process is started with the parent's SLACK_* and
    RATIONALE_MCP_* variables passed through explicitly. The MCP SDK gives a
    child a minimal environment by default, which is the right security
    posture but means a Slack server would otherwise start without its token.

    Exercised end-to-end against a real MCP server in tests/integration
    (a local one that records what it receives). Posting into an actual
    Slack workspace additionally needs that server's credentials; see the
    note in DEMO_SCRIPT.md.
    """

    name = "mcp"
    live = True

    def __init__(self, command: str = None, tool: str = None, channel: str = None,
                 passthrough=None):
        self.command = command or os.environ.get("RATIONALE_MCP_COMMAND", "")
        self.tool = tool or os.environ.get("RATIONALE_MCP_TOOL", "")
        self.channel = channel or os.environ.get("RATIONALE_MCP_CHANNEL", "")
        self.passthrough = passthrough or ("SLACK_", "RATIONALE_MCP_", "ECHO_MCP_")
        self.last_tool = None

    def available(self) -> bool:
        try:
            import mcp  # noqa: F401
        except ImportError:
            return False
        return bool(self.command)

    def _child_env(self) -> dict:
        from mcp.client.stdio import get_default_environment
        env = get_default_environment()
        for k, v in os.environ.items():
            if k.startswith(tuple(self.passthrough)):
                env[k] = v
        return env

    def send(self, message: dict) -> dict:
        if not self.available():
            return {"ok": False, "transport": self.name,
                    "detail": "no MCP server configured (set RATIONALE_MCP_COMMAND)"}
        try:
            import asyncio
            return asyncio.run(self._send(message))
        except Exception as e:          # a failed send must never break the app
            return {"ok": False, "transport": self.name,
                    "detail": f"{type(e).__name__}: {e}"}

    async def _send(self, message: dict) -> dict:
        import shlex

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        parts = shlex.split(self.command, posix=False)
        parts = [p.strip('"') for p in parts]
        params = StdioServerParameters(command=parts[0], args=parts[1:],
                                       env=self._child_env())
        text = f"*{message['subject']}*\n\n{message['body']}"
        destination = self.channel or message.get("to", "")

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                tool = _pick_tool(listing.tools, self.tool)
                if tool is None:
                    names = [t.name for t in listing.tools]
                    return {"ok": False, "transport": self.name,
                            "detail": f"no message-posting tool found; server offers {names}"}
                args = _map_args(tool, destination, text)
                required = set((tool.inputSchema or {}).get("required", []) or [])
                missing = required - set(args)
                if missing:
                    return {"ok": False, "transport": self.name,
                            "detail": f"{tool.name} requires {sorted(missing)} which the "
                                      "adapter cannot supply"}
                self.last_tool = tool.name
                result = await session.call_tool(tool.name, args)

        content = "".join(getattr(c, "text", "") for c in (result.content or []))
        return {"ok": not getattr(result, "isError", False), "transport": self.name,
                "tool": tool.name, "detail": content[:200]}


def get_transport():
    """DryRun unless a live transport is explicitly configured."""
    if os.environ.get("RATIONALE_DISPATCH") == "mcp":
        return MCPTransport()
    return DryRunTransport()
