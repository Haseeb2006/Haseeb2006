"""jarvis-mcp entrypoint.

Tools are registered here and nowhere else, so this file is the whole inventory of
what the assistant can do to the machine — and what tier each capability sits at.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context, MCPServer

from . import __version__
from .policy import Tier, guarded
from .tools import apps, files, shortcuts, system

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
async def set_volume(level: int) -> dict[str, Any]:
    """Set the output volume to a percentage from 0 to 100.

    Args:
        level: Volume percentage. 0 mutes.
    """
    return await system.set_volume(level=level)


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
