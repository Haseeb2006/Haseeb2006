"""AMBER — launch applications."""

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
