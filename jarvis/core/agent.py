"""The agent loop.

Jarvis is an MCP *client*. It launches the same server Claude Desktop launches,
converts its tools into Claude tools, and runs the conversation. Nothing about a
tool is written twice — the server is the single definition of what this machine
can do.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import anthropic

from . import settings

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
    """One Claude conversation over a Machine's tools."""

    def __init__(
        self,
        machine: Any,
        *,
        on_tool: ToolReporter | None = None,
        client: Any | None = None,
    ) -> None:
        self._machine = machine
        self._on_tool = on_tool
        self._client = client or anthropic.AsyncAnthropic()
        self.messages: list[dict[str, Any]] = []
        self._fallbacks_supported = True

    @property
    def tool_names(self) -> list[str]:
        return self._machine.tool_names

    def _request(self) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": settings.model(),
            "max_tokens": settings.max_tokens(),
            "max_iterations": settings.max_iterations(),
            "system": build_system(),
            "tools": self._machine.claude_tools,
            # Adaptive thinking, with effort as the cost dial. `budget_tokens` is
            # rejected outright on this model family.
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": settings.effort()},
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

    async def _remembered(self, text: str) -> str:
        """Memories worth putting in front of Claude for this message.

        Injected into the user turn, never the system prompt: what is recalled
        changes every message, and a varying system prompt would invalidate the
        cached prefix on every request.
        """
        try:
            result = await self._machine.call("recall", {"query": text, "limit": 5})
        except Exception:
            return ""  # memory is an enhancement; never fail a turn over it
        memories = (result or {}).get("memories") or []
        if not memories:
            return ""
        lines = "\n".join(f"- {m['text']}" for m in memories)
        return f"<remembered>\n{lines}\n</remembered>"

    async def ask(self, text: str) -> str:
        """Send one user message and return Jarvis's reply."""
        # Taken before the user turn is added: a failed turn rolls back to the
        # last good state, rather than leaving a user message with no reply
        # (two user turns in a row is not a valid conversation).
        snapshot = list(self.messages)
        content = [{"type": "text", "text": volatile_context()}]
        remembered = await self._remembered(text)
        if remembered:
            content.append({"type": "text", "text": remembered})
        content.append({"type": "text", "text": text})
        self.messages.append({"role": "user", "content": content})

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
