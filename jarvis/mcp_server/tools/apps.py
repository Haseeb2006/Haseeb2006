"""AMBER — launch and quit applications."""

from __future__ import annotations

from typing import Any

from .. import macos


async def open_app(name: str) -> dict[str, Any]:
    """Launch a Mac application by name and bring it to the front.

    Accepts the name as it appears in Finder, with or without ".app" —
    "Safari", "Visual Studio Code", "Spotify". If the app is already running it is
    brought forward rather than relaunched.

    Args:
        name: The application's name.
    """
    macos.require_macos("open_app")
    name = name.strip().removesuffix(".app").strip()
    if not name:
        raise ValueError("name must not be empty")

    result = await macos.run("open", "-a", name)
    if not result.ok:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Could not open {name!r}: {detail}")

    return {"opened": name, "status": "frontmost"}


QUIT_TIMEOUT = 20.0


def parse_running(output: str) -> list[str]:
    """Application names from System Events, which returns them comma-separated."""
    return [name.strip() for name in output.split(",") if name.strip()]


async def running_apps() -> list[str]:
    result = await macos.osascript_argv(
        [
            'tell application "System Events" to get name of every application '
            "process whose background only is false"
        ]
    )
    if not result.ok:
        raise RuntimeError(
            result.stderr.strip()
            or "Could not list running apps — this server may need Accessibility "
               "permission in System Settings > Privacy & Security > Accessibility."
        )
    return parse_running(result.stdout)


async def quit_app(name: str) -> dict[str, Any]:
    """Quit a running Mac application, letting it save and close normally.

    Matches the name case-insensitively against what is actually running. If the
    app is not running it says so rather than starting it.

    Args:
        name: The application's name, e.g. "WhatsApp" or "Safari".
    """
    macos.require_macos("quit_app")
    name = name.strip().removesuffix(".app").strip()
    if not name:
        raise ValueError("name must not be empty")

    running = await running_apps()
    match = next((app for app in running if app.casefold() == name.casefold()), None)
    if match is None:
        # Quitting a non-running app through AppleScript can *launch* it first,
        # which would be a baffling outcome. Stop here instead.
        listed = ", ".join(sorted(running)[:12]) or "(none)"
        return {"quit": None, "already_closed": True, "running": listed,
                "note": f"{name!r} is not running. Currently open: {listed}"}

    result = await macos.osascript_argv(
        ["on run argv", "tell application (item 1 of argv) to quit", "end run"],
        match,
        timeout=QUIT_TIMEOUT,
    )
    if not result.ok:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Could not quit {match!r}: {detail}")
    return {"quit": match, "already_closed": False}
