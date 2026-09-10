"""Answering the server's RED confirmations at the terminal.

The MCP server cannot prompt for itself — it asks the *client*, through
elicitation. Claude Desktop shows a dialog; here, we ask on stdin. This is what
makes the RED tier a real gate in our own loop rather than a flat refusal.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp import types

YES = {"y", "yes"}


def _describe(params: Any) -> str:
    return (getattr(params, "message", "") or "").strip() or "Allow this action?"


async def ask_terminal(context: Any, params: Any) -> types.ElicitResult | types.ErrorData:
    """Put a RED action to the user and turn the answer into an ElicitResult."""
    # URL-mode elicitation asks the user to visit a link; nothing here needs it,
    # and silently accepting an unknown mode would defeat the point of the gate.
    if getattr(params, "mode", "form") == "url" or hasattr(params, "url"):
        return types.ErrorData(
            code=types.INVALID_REQUEST,
            message="This client only supports form-mode confirmation.",
        )

    prompt = f"\n  \033[33m{_describe(params)}\033[0m\n  Allow? [y/N] "
    try:
        # input() blocks; keep it off the event loop so the session stays alive.
        answer = await asyncio.to_thread(input, prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return types.ElicitResult(action="cancel")

    if answer.strip().lower() not in YES:
        return types.ElicitResult(action="decline")

    # The server's schema asks for a boolean `confirm`; fill whatever booleans it
    # requested rather than assuming the field name.
    schema = getattr(params, "requestedSchema", None) or {}
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    content: dict[str, Any] = {name: True for name in properties} or {"confirm": True}
    return types.ElicitResult(action="accept", content=content)


async def deny_all(context: Any, params: Any) -> types.ElicitResult:
    """Non-interactive stand-in: refuse everything rather than auto-approving."""
    return types.ElicitResult(action="decline")
