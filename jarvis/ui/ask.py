"""One-shot entry points: `jarvis-ask` for the shell, `jarvis-prompt` for a hotkey.

Both go through the daemon, which is the point — the answer should arrive at
keystroke speed, not after a cold start.
"""

from __future__ import annotations

import asyncio
import sys

from core import client, protocol

NO_DAEMON = """The jarvis daemon is not running.

  uv run jarvisd                      # start it in this terminal
  uv run python install_agent.py      # or have launchd keep it running"""


async def _dialog(script_args: list[str], *args: str) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        "osascript", *script_args, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await process.communicate()
    return process.returncode or 0, out.decode("utf-8", "replace").strip()


def parse_dialog_text(output: str) -> str | None:
    """Pull the typed text out of `display dialog`'s reply line.

    It answers `text returned:hello, button returned:Ask` — and the typed text
    may itself contain a comma, so split on the button marker, not on commas.
    """
    marker = "text returned:"
    if marker not in output:
        return None
    typed = output.split(marker, 1)[1]
    for tail in (", button returned:", "button returned:"):
        if tail in typed:
            typed = typed.rsplit(tail, 1)[0]
            break
    return typed.strip() or None


async def prompt_for_text() -> str | None:
    """A Spotlight-ish input box. None if the user cancelled."""
    code, out = await _dialog(
        [
            "-e", "on run argv",
            # `activate` brings the dialog to the front; without it the box can
            # open behind whatever you were looking at when you hit the key.
            "-e", "activate",
            "-e", 'display dialog "" with title (item 1 of argv) '
                  'default answer "" buttons {"Cancel", "Ask"} default button "Ask"',
            "-e", "end run",
        ],
        "Jarvis",
    )
    if code != 0:
        return None
    return parse_dialog_text(out)


async def show(text: str) -> None:
    # `display dialog` rather than a notification: notifications truncate, and
    # an answer you cannot finish reading is not an answer.
    await _dialog(
        [
            "-e", "on run argv",
            "-e", "activate",
            "-e", 'display dialog (item 2 of argv) with title (item 1 of argv) '
                  'buttons {"OK"} default button "OK"',
            "-e", "end run",
        ],
        "Jarvis",
        text[:4000],
    )


async def run_prompt() -> int:
    """Hotkey flow: ask, answer, both in native dialogs."""
    text = await prompt_for_text()
    if not text:
        return 0
    try:
        answer = await client.ask(text)
    except client.NoDaemon:
        await show(f"The jarvis daemon is not running.\n\n{protocol.socket_path()}")
        return 1
    except Exception as exc:  # noqa: BLE001
        await show(f"{type(exc).__name__}: {exc}")
        return 1
    await show(answer.text)
    return 0


async def run_ask(argv: list[str]) -> int:
    """Shell flow: `jarvis-ask volume 40`."""
    text = " ".join(argv).strip()
    if not text:
        print("usage: jarvis-ask <message>", file=sys.stderr)
        return 2
    try:
        answer = await client.ask(text)
    except client.NoDaemon:
        print(NO_DAEMON, file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(answer.text)
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(run_ask(sys.argv[1:])))


def prompt() -> None:
    raise SystemExit(asyncio.run(run_prompt()))
