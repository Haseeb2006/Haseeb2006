"""The MCP connection, shared by every tier.

Tier 0 calls tools straight through `call()`. Tier 2 hands `claude_tools` to the
model. One server process either way — the tools are defined once.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Awaitable, Callable

from anthropic.lib.tools.mcp import async_mcp_tool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .confirm import ask_terminal

CACHE: dict[str, str] = {"type": "ephemeral"}
SERVER_LOG = Path("~/.jarvis/server.log").expanduser()


class ToolFailed(Exception):
    """A tool call came back as an error result."""


class Machine:
    def __init__(
        self,
        elicitation_callback: Callable[..., Awaitable[Any]] | None = None,
        errlog: Any = None,
    ) -> None:
        self._elicit = elicitation_callback or ask_terminal
        # The server logs to stderr, which the client inherits — its INFO lines
        # would land in the middle of the user's prompt. Kept, but out of the way.
        self._errlog = errlog
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None
        self.claude_tools: list[Any] = []
        self.tool_names: list[str] = []

    async def __aenter__(self) -> "Machine":
        SERVER_LOG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_server.server"],
            env=dict(os.environ),
        )
        errlog = self._errlog
        if errlog is None:
            errlog = self._stack.enter_context(
                open(SERVER_LOG, "a", encoding="utf-8", buffering=1)
            )
        read, write = await self._stack.enter_async_context(
            stdio_client(params, errlog=errlog)
        )
        self._session = await self._stack.enter_async_context(
            ClientSession(read, write, elicitation_callback=self._elicit)
        )
        await self._session.initialize()

        discovered = (await self._session.list_tools()).tools
        self.tool_names = [tool.name for tool in discovered]
        # One breakpoint, on the last tool: cache_control ends a prefix, and the
        # tool block is that prefix.
        self.claude_tools = [
            async_mcp_tool(
                tool,
                self._session,
                cache_control=CACHE if index == len(discovered) - 1 else None,
            )
            for index, tool in enumerate(discovered)
        ]
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._stack.aclose()

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool directly, with no model involved. Raises ToolFailed."""
        if self._session is None:
            raise RuntimeError("Machine is not connected")

        result = await self._session.call_tool(name, arguments)
        text = "\n".join(
            block.text for block in result.content if getattr(block, "type", "") == "text"
        )
        if result.is_error:
            raise ToolFailed(text or f"{name} failed")

        structured = getattr(result, "structured_content", None)
        if structured:
            return structured
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text
