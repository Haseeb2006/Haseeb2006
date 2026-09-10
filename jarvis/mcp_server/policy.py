"""Permission tiers.

GREEN  read-only ............ runs
AMBER  reversible write ..... runs, audited
RED    destructive/outbound . allowlisted, or confirmed by the user, or refused

The RED path matters most. An MCP server has no terminal of its own, so it cannot
prompt directly — but MCP 2.x clients may support *elicitation*, which lets a tool
ask the user a question mid-call. So RED resolves in three steps:

  1. pre-allowlisted for this specific target  -> run
  2. client supports elicitation               -> ask, run only on "accept"
  3. otherwise                                 -> refuse, and say how to allowlist

Step 3 is the important one: a client that cannot ask gets a refusal, never a
silent execution.
"""

from __future__ import annotations

import functools
import inspect
from enum import Enum
from typing import Any, Callable

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from . import audit
from .config import PathNotAllowed
from .macos import NotMacOS


class Tier(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class Refused(Exception):
    """The policy layer declined to run the tool."""


# Failures whose message is *for the model*: a refusal and how to lift it, a bad
# shortcut name, a path outside the allowlist. MCP masks the text of any other
# exception as a bare "Error executing tool X" so server internals cannot leak, so
# these are re-raised as `ToolError` — the one class whose message is passed
# through. A genuine crash keeps that masking; it is a bug, not an answer.
EXPLANATORY = (
    ValueError,
    NotMacOS,
    PathNotAllowed,
    TimeoutError,
    FileNotFoundError,
    RuntimeError,
)


class ConfirmAction(BaseModel):
    """Schema for the confirmation prompt sent to the client."""

    confirm: bool = Field(
        default=False,
        description="Set true to run this action. Anything else cancels it.",
    )


async def confirm_red(ctx: Any, *, tool: str, summary: str) -> None:
    """Gate a RED action behind user confirmation. Raises `Refused` if not granted."""
    supported = False
    if ctx is not None:
        try:
            caps = ctx.client_capabilities
            # Presence, not truthiness: the capability may be an empty object
            # (`{}` or a field-less model), which is falsy but means "supported".
            supported = caps is not None and getattr(caps, "elicitation", None) is not None
        except (AttributeError, ValueError, LookupError):
            supported = False

    if not supported:
        raise Refused(
            f"{summary}\n\n"
            "This is a RED (destructive or outbound) action and this client cannot "
            "show a confirmation prompt, so it was refused. To permit it, add the "
            "target to the allowlist and restart the server — for shortcuts:\n"
            '  export JARVIS_ALLOWED_SHORTCUTS="Name One,Name Two"'
        )

    result = await ctx.elicit(
        message=f"Allow this RED action?\n\n{summary}",
        schema=ConfirmAction,
    )
    action = getattr(result, "action", None)
    data = getattr(result, "data", None)
    if action != "accept" or data is None or not data.confirm:
        raise Refused(f"Cancelled by the user: {summary}")


def guarded(tier: Tier) -> Callable[[Callable], Callable]:
    """Audit every call to the wrapped tool and tag it with its tier.

    The wrapper deliberately preserves the wrapped function's signature so the MCP
    server still derives the correct input schema and still injects `Context`.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            loggable = {k: v for k, v in kwargs.items() if k != "ctx"}
            try:
                result = await func(*args, **kwargs)
            except Refused as exc:
                audit.record(
                    tool=func.__name__,
                    tier=tier.value,
                    outcome="refused",
                    arguments=loggable,
                    detail=str(exc),
                )
                raise ToolError(str(exc)) from exc
            except EXPLANATORY as exc:
                audit.record(
                    tool=func.__name__,
                    tier=tier.value,
                    outcome="error",
                    arguments=loggable,
                    detail=f"{type(exc).__name__}: {exc}",
                )
                raise ToolError(str(exc)) from exc
            except Exception as exc:
                audit.record(
                    tool=func.__name__,
                    tier=tier.value,
                    outcome="crash",
                    arguments=loggable,
                    detail=f"{type(exc).__name__}: {exc}",
                )
                raise
            audit.record(
                tool=func.__name__,
                tier=tier.value,
                outcome="ok",
                arguments=loggable,
            )
            return result

        # `functools.wraps` sets __wrapped__, which inspect.signature follows —
        # assert it so a future refactor cannot silently break schema generation.
        assert inspect.signature(wrapper) == inspect.signature(func)
        return wrapper

    return decorator
