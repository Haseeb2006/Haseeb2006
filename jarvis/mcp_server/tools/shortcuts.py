"""Shortcuts — the entitlement bypass.

Anything that would otherwise need entitlements or code signing (Messages,
Reminders, HomeKit, Focus modes) gets built once in the Shortcuts app and called
by name from here.

That power is exactly why running one is RED: a Shortcut can send a message or
turn off the lights. `list_shortcuts` is GREEN — reading the names is harmless.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .. import config, macos, policy

RUN_TIMEOUT = 120.0


async def _names() -> list[str]:
    result = await macos.run("shortcuts", "list", timeout=20.0)
    if not result.ok:
        raise RuntimeError(result.stderr.strip() or "`shortcuts list` failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


async def list_shortcuts() -> dict[str, Any]:
    """List the Shortcuts available on this Mac, by name.

    Call this before `run_shortcut` to find the exact name — matching is
    case-insensitive but otherwise literal.
    """
    macos.require_macos("list_shortcuts")
    names = await _names()
    allowed = config.allowed_shortcuts()
    return {
        "count": len(names),
        "shortcuts": [
            {"name": name, "preapproved": name.casefold() in allowed}
            for name in names
        ],
        "note": (
            "Shortcuts not marked preapproved need confirmation before they run."
        ),
    }


async def run_shortcut(
    name: str,
    input_text: str = "",
    ctx: Any = None,
) -> dict[str, Any]:
    """Run a Shortcut by name and return whatever it outputs.

    This is a RED action — a Shortcut can send messages, change settings, or
    control devices. It runs only if the name is pre-approved via
    JARVIS_ALLOWED_SHORTCUTS, or if you confirm it when prompted.

    Args:
        name: Exact name of the Shortcut, as shown by `list_shortcuts`.
        input_text: Optional text passed to the Shortcut as its input.
    """
    macos.require_macos("run_shortcut")
    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")

    # Resolve against the real list first, so a typo is a clear error rather than
    # a confirmation prompt for something that does not exist.
    available = await _names()
    match = next((n for n in available if n.casefold() == name.casefold()), None)
    if match is None:
        raise ValueError(
            f"No Shortcut named {name!r}. Available: {', '.join(available) or '(none)'}"
        )

    if match.casefold() not in config.allowed_shortcuts():
        summary = f"Run the Shortcut {match!r}"
        if input_text:
            preview = input_text if len(input_text) <= 200 else input_text[:200] + "…"
            summary += f" with input: {preview!r}"
        await policy.confirm_red(ctx, tool="run_shortcut", summary=summary)

    with tempfile.TemporaryDirectory(prefix="jarvis-shortcut-") as tmp:
        argv = ["shortcuts", "run", match]
        if input_text:
            infile = Path(tmp) / "input.txt"
            infile.write_text(input_text, encoding="utf-8")
            argv += ["-i", str(infile)]
        outfile = Path(tmp) / "output"
        argv += ["-o", str(outfile)]

        result = await macos.run(*argv, timeout=RUN_TIMEOUT)
        if not result.ok:
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"Shortcut {match!r} failed: {detail}")

        output = ""
        if outfile.exists():
            output = outfile.read_text(encoding="utf-8", errors="replace").strip()

    return {
        "shortcut": match,
        "output": output or None,
        "stdout": result.stdout.strip() or None,
    }
