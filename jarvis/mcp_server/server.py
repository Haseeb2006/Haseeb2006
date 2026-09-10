"""jarvis-mcp entrypoint.

Tools are registered here and nowhere else, so this file is the whole inventory of
what the assistant can do to the machine — and what tier each capability sits at.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context, MCPServer

from . import __version__
from .policy import Tier, guarded
from .tools import apps, controls, files, media, shortcuts, system

server = MCPServer(
    name="jarvis",
    version=__version__,
    instructions=(
        "Tools for reading and controlling this Mac. Tools are tiered: GREEN is "
        "read-only, AMBER makes a reversible change, RED is destructive or sends "
        "something outward and needs the user's confirmation. Prefer "
        "`list_shortcuts` before `run_shortcut` so you use an exact name."
    ),
)


@server.tool(annotations={"readOnlyHint": True})
@guarded(Tier.GREEN)
async def system_status() -> dict[str, Any]:
    """Report battery, volume, Wi-Fi network, free disk, uptime, and frontmost app."""
    return await system.system_status()


@server.tool(annotations={"readOnlyHint": True})
@guarded(Tier.GREEN)
async def search_files(query: str, limit: int = 20) -> dict[str, Any]:
    """Search for files by name inside the allowlisted folders.

    Args:
        query: Text to match in the filename, e.g. "invoice" or "resume.pdf".
        limit: Maximum results to return (1-50).
    """
    return await files.search_files(query=query, limit=limit)


@server.tool(annotations={"readOnlyHint": True})
@guarded(Tier.GREEN)
async def list_shortcuts() -> dict[str, Any]:
    """List this Mac's Shortcuts by name, flagging which are pre-approved to run."""
    return await shortcuts.list_shortcuts()


@server.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@guarded(Tier.AMBER)
async def open_app(name: str) -> dict[str, Any]:
    """Launch a Mac application and bring it to the front.

    Args:
        name: The application's name, e.g. "Safari" or "Visual Studio Code".
    """
    return await apps.open_app(name=name)


@server.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@guarded(Tier.AMBER)
async def quit_app(name: str) -> dict[str, Any]:
    """Quit a running application, letting it save and close normally.

    Args:
        name: The application's name, e.g. "WhatsApp" or "Safari".
    """
    return await apps.quit_app(name=name)


@server.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@guarded(Tier.AMBER)
async def set_volume(level: int) -> dict[str, Any]:
    """Set the output volume to a percentage from 0 to 100.

    Args:
        level: Volume percentage. 0 mutes.
    """
    return await system.set_volume(level=level)


@server.tool(annotations={"readOnlyHint": True})
@guarded(Tier.GREEN)
async def now_playing() -> dict[str, Any]:
    """Report what Apple Music is currently playing, if anything."""
    return await media.now_playing()


@server.tool(annotations={"readOnlyHint": True})
@guarded(Tier.GREEN)
async def read_clipboard() -> dict[str, Any]:
    """Read the text currently on the clipboard."""
    return await controls.read_clipboard()


@server.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@guarded(Tier.AMBER)
async def media_control(action: str) -> dict[str, Any]:
    """Control Apple Music playback.

    Args:
        action: One of play, pause, playpause, next, previous.
    """
    return await media.media_control(action=action)


@server.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@guarded(Tier.AMBER)
async def change_volume(delta: int) -> dict[str, Any]:
    """Raise or lower the volume by a number of percentage points.

    Args:
        delta: Points to change by. Positive is louder, negative is quieter.
    """
    return await controls.change_volume(delta=delta)


@server.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@guarded(Tier.AMBER)
async def set_mute(muted: bool) -> dict[str, Any]:
    """Mute or unmute the output.

    Args:
        muted: True to mute, False to unmute.
    """
    return await controls.set_mute(muted=muted)


@server.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@guarded(Tier.AMBER)
async def set_wifi(on: bool) -> dict[str, Any]:
    """Turn Wi-Fi on or off.

    Args:
        on: True to turn Wi-Fi on, False to turn it off.
    """
    return await controls.set_wifi(on=on)


@server.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@guarded(Tier.AMBER)
async def set_dark_mode(on: bool) -> dict[str, Any]:
    """Turn the system's dark appearance on or off.

    Args:
        on: True for dark mode, False for light mode.
    """
    return await controls.set_dark_mode(on=on)


@server.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@guarded(Tier.AMBER)
async def write_clipboard(text: str) -> dict[str, Any]:
    """Put text on the clipboard, replacing what was there.

    Args:
        text: The text to copy.
    """
    return await controls.write_clipboard(text=text)


@server.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@guarded(Tier.AMBER)
async def lock_screen() -> dict[str, Any]:
    """Lock the screen immediately. There is no unlock — that needs a password."""
    return await controls.lock_screen()


@server.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
@guarded(Tier.RED)
async def run_shortcut(
    name: str,
    input_text: str = "",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Run a Shortcut by name. Needs confirmation unless pre-approved.

    Args:
        name: Exact name of the Shortcut, as shown by `list_shortcuts`.
        input_text: Optional text passed to the Shortcut as its input.
    """
    return await shortcuts.run_shortcut(name=name, input_text=input_text, ctx=ctx)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
