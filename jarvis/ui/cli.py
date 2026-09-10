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
            if text in ("/quit", "/exit"):
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
            except anthropic.APIStatusError as exc:
                print(f"{YELLOW}  api error {exc.status_code}: {exc.message}{OFF}")
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
