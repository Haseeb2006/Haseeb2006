"""The terminal front end.

    uv run jarvis
"""

from __future__ import annotations

import asyncio
import sys

import anthropic

from core import settings
from core.agent import Jarvis

DIM, YELLOW, BOLD, OFF = "\033[2m", "\033[33m", "\033[1m", "\033[0m"
BANNER = f"{BOLD}jarvis{OFF} {DIM}— ctrl-d or /quit to exit, /help for commands{OFF}"


def show_tool(name: str, arguments: dict) -> None:
    """Print each tool call as it happens, so the machine is never a black box."""
    shown = ", ".join(f"{k}={v!r}" for k, v in arguments.items() if v not in ("", None))
    print(f"{DIM}  · {name}({shown}){OFF}", flush=True)


HELP = """  /tools    list the tools Jarvis can use
  /reset    forget this conversation
  /quit     exit"""

# People type `quit`, not `/quit`. Sending that to the API costs a request and
# returns a puzzled answer, so treat the bare words as the command too.
LEAVE = {"/quit", "/exit", "quit", "exit", "bye", "q"}


def api_message(exc: anthropic.APIStatusError) -> str:
    """The human sentence out of an API error, without the JSON wrapper."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    return getattr(exc, "message", None) or str(exc)


def fatal_hint(exc: anthropic.APIStatusError, message: str) -> str | None:
    """What to do about an error that will not fix itself.

    Billing and auth failures repeat identically on every turn. Staying in the
    loop just reprints the same wall of JSON per keystroke, so these end the
    session with the one thing that actually helps.
    """
    lowered = message.lower()
    if "credit balance" in lowered or "billing" in lowered:
        return (
            "Add credits at console.anthropic.com > Plans & Billing.\n"
            "  Nothing is wrong with jarvis — the account just cannot be charged."
        )
    if isinstance(exc, anthropic.AuthenticationError) or "x-api-key" in lowered:
        return (
            "Check ANTHROPIC_API_KEY. Keys are at console.anthropic.com > API keys."
        )
    if isinstance(exc, anthropic.PermissionDeniedError):
        return f"This key may not have access to {settings.MODEL}."
    return None


async def converse() -> int:
    if not settings.has_api_key():
        print("ANTHROPIC_API_KEY is not set.\n")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        print("\nPut it in your shell profile so it survives new terminals.")
        return 1

    print(BANNER)
    async with Jarvis(on_tool=show_tool) as jarvis:
        print(f"{DIM}{len(jarvis.tool_names)} tools · {settings.MODEL} "
              f"· effort {settings.EFFORT}{OFF}\n")

        while True:
            try:
                text = (await asyncio.to_thread(input, f"{BOLD}› {OFF}")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0

            if not text:
                continue
            if text.lower() in LEAVE:
                return 0
            if text == "/help":
                print(HELP)
                continue
            if text == "/tools":
                print("\n".join(f"  {name}" for name in jarvis.tool_names))
                continue
            if text == "/reset":
                jarvis.messages.clear()
                print(f"{DIM}  conversation cleared{OFF}")
                continue

            try:
                reply = await jarvis.ask(text)
            except anthropic.RateLimitError:
                print(f"{YELLOW}  rate limited — wait a moment and try again{OFF}")
                continue
            except anthropic.APIStatusError as exc:
                message = api_message(exc)
                print(f"{YELLOW}  {message}{OFF}")
                hint = fatal_hint(exc, message)
                if hint:
                    print(f"{DIM}  {hint}{OFF}")
                    return 1
                continue
            except anthropic.APIConnectionError as exc:
                print(f"{YELLOW}  cannot reach the API: {exc}{OFF}")
                continue
            except KeyboardInterrupt:
                print(f"\n{DIM}  interrupted{OFF}")
                continue

            print(f"\n{reply}\n")


def main() -> None:
    try:
        sys.exit(asyncio.run(converse()))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
