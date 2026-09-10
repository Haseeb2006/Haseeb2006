"""Thin, safe wrappers around the macOS command-line surface.

Commands are always run as an argument list — never through a shell — so a filename
containing `;` or `$(...)` is inert. `osascript -e` is the one place user text could
reach an interpreter, so nothing user-supplied is ever interpolated into a script
here; scripts are fixed strings and arguments go through `argv`.
"""

from __future__ import annotations

import asyncio
import platform
import shutil
from dataclasses import dataclass

DEFAULT_TIMEOUT = 10.0


class NotMacOS(Exception):
    """Raised when a macOS-only tool is invoked on another platform."""


def is_macos() -> bool:
    return platform.system() == "Darwin"


def require_macos(tool: str) -> None:
    if not is_macos():
        raise NotMacOS(
            f"{tool} needs macOS; this server is running on {platform.system()}."
        )


@dataclass(frozen=True)
class Completed:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def text(self) -> str:
        return self.stdout.strip()


async def run(
    *argv: str,
    timeout: float = DEFAULT_TIMEOUT,
    stdin: bytes | None = None,
) -> Completed:
    """Run a command with no shell and a hard timeout."""
    if shutil.which(argv[0]) is None:
        raise FileNotFoundError(f"{argv[0]} not found on PATH")

    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"{argv[0]} timed out after {timeout}s") from None

    return Completed(
        returncode=proc.returncode or 0,
        stdout=out.decode("utf-8", "replace"),
        stderr=err.decode("utf-8", "replace"),
    )


async def osascript(script: str, timeout: float = DEFAULT_TIMEOUT) -> Completed:
    """Run a *fixed* AppleScript. Never build this string from user input."""
    return await run("osascript", "-e", script, timeout=timeout)


async def osascript_argv(lines: list[str], *args: str, timeout: float = DEFAULT_TIMEOUT) -> Completed:
    """Run an AppleScript that takes its inputs as `argv`, never as interpolated text.

    The script body is a fixed list of lines; user-supplied values arrive through
    `on run argv`, so a name containing quotes or AppleScript syntax is data.
    """
    for arg in args:
        # An argument starting with "-" would be read as an option by osascript.
        if arg.startswith("-"):
            raise ValueError(f"refusing to pass {arg!r} as a script argument")
    argv = ["osascript"]
    for line in lines:
        argv += ["-e", line]
    return await run(*argv, *args, timeout=timeout)


async def probe(coro) -> str | None:
    """Await a probe, returning None instead of raising.

    `system_status` gathers half a dozen independent facts; one unavailable probe
    (no battery on a Mac mini, Wi-Fi off) must not fail the whole call.
    """
    try:
        return await coro
    except (OSError, TimeoutError, ValueError, NotMacOS):
        return None
