"""The agent loop.

Jarvis is an MCP *client*. It launches the same server Claude Desktop launches,
converts its tools into Claude tools, and runs the conversation. Nothing about a
tool is written twice — the server is the single definition of what this machine
can do.
"""

from __future__ import annotations

import os
import sys
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

import anthropic
from anthropic.lib.tools.mcp import async_mcp_tool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from . import settings
from .confirm import ask_terminal

PROMPTS = Path(__file__).resolve().parent / "prompts"
CACHE: dict[str, str] = {"type": "ephemeral"}

ToolReporter = Callable[[str, dict[str, Any]], None]


def _read_prompt(name: str) -> str:
    path = PROMPTS / name
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def build_system() -> list[dict[str, Any]]:
    """The stable half of the prompt.

    Everything here is identical turn to turn, so it sits before the cache
    breakpoint. Anything that changes per turn must go in the messages instead —
    a single varying byte here would invalidate the cached prefix every request.
    """
    blocks = [{"type": "text", "text": _read_prompt("system.md")}]
    profile = _read_prompt("profile.md")
    if profile:
        blocks.append({"type": "text", "text": f"# About the user\n\n{profile}"})
    blocks[-1]["cache_control"] = CACHE
    return blocks


def volatile_context() -> str:
    """Facts that change. Goes after the last breakpoint, never in the system prompt."""
    return f"[{datetime.now().strftime('%A %d %B %Y, %H:%M')}]"


def _text_of(message: Any) -> str:
    return "\n".join(
        block.text for block in message.content if getattr(block, "type", "") == "text"
    ).strip()


class Jarvis:
    """One conversation, holding one MCP server subprocess open for its lifetime."""

    def __init__(
        self,
        *,
        on_tool: ToolReporter | None = None,
        elicitation_callback: Callable[..., Awaitable[Any]] | None = None,
        client: Any | None = None,
    ) -> None:
        self._on_tool = on_tool
        self._elicit = elicitation_callback or ask_terminal
        self._client = client or anthropic.AsyncAnthropic()
        self._stack = AsyncExitStack()
        self._tools: list[Any] = []
        self.messages: list[dict[str, Any]] = []
        self.tool_names: list[str] = []
        self._fallbacks_supported = True

    async def __aenter__(self) -> "Jarvis":
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_server.server"],
            env=dict(os.environ),
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        session = await self._stack.enter_async_context(
            ClientSession(read, write, elicitation_callback=self._elicit)
        )
        await session.initialize()

        discovered = (await session.list_tools()).tools
        self.tool_names = [tool.name for tool in discovered]
        # Mark only the final tool: cache_control ends a prefix, and the whole
        # tool block is that prefix. Marking every tool wastes breakpoints.
        self._tools = [
            async_mcp_tool(
                tool,
                session,
                cache_control=CACHE if index == len(discovered) - 1 else None,
            )
            for index, tool in enumerate(discovered)
        ]
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._stack.aclose()

    def _request(self) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": settings.MODEL,
            "max_tokens": settings.MAX_TOKENS,
            "max_iterations": settings.MAX_ITERATIONS,
            "system": build_system(),
            "tools": self._tools,
            # Adaptive thinking, with effort as the cost dial. `budget_tokens` is
            # rejected outright on this model family.
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": settings.EFFORT},
        }
        if self._fallbacks_supported:
            # Opus 5 can decline a request outright; let the server re-route it
            # rather than handing back a dead end.
            request["betas"] = [settings.FALLBACK_BETA]
            request["fallbacks"] = "default"
        return request

    async def _drive(self) -> Any:
        """Run one turn to completion, mirroring history as the runner goes.

        The runner keeps its own copy of the conversation and does not expose it,
        so each assistant turn and its tool results are appended here — otherwise
        the next turn would start from nothing.
        """
        runner = self._client.beta.messages.tool_runner(
            messages=list(self.messages), **self._request()
        )
        last = None
        async for message in runner:
            last = message
            self.messages.append({"role": "assistant", "content": message.content})

            for block in message.content:
                if getattr(block, "type", "") == "tool_use" and self._on_tool:
                    self._on_tool(block.name, block.input or {})

            # Cached by the runner: the tools themselves still run only once.
            response = runner.generate_tool_call_response()
            if response is not None:
                self.messages.append(response)
        return last

    async def ask(self, text: str) -> str:
        """Send one user message and return Jarvis's reply."""
        # Taken before the user turn is added: a failed turn rolls back to the
        # last good state, rather than leaving a user message with no reply
        # (two user turns in a row is not a valid conversation).
        snapshot = list(self.messages)
        self.messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": volatile_context()},
                    {"type": "text", "text": text},
                ],
            }
        )

        # A turn that dies partway also leaves an assistant tool_use with no
        # matching result, which the API rejects on every later request.
        try:
            last = await self._drive()
        except anthropic.BadRequestError as exc:
            self.messages = snapshot
            # Server-side fallback is opt-in per account. If it is not enabled,
            # drop it and run the turn without, rather than failing the session.
            if not self._fallbacks_supported or "fallback" not in str(exc).lower():
                raise
            self._fallbacks_supported = False
            last = await self._drive()
        except Exception:
            self.messages = snapshot
            raise

        if last is None:
            return "(no response)"
        if getattr(last, "stop_reason", None) == "refusal":
            return "I can't help with that one."
        return _text_of(last) or "(done)"
