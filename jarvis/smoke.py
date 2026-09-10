"""Connect to the server the way a client does, and print what it exposes.

    uv run python smoke.py

Runs on any platform: off macOS the read-only tools report that plainly instead of
pretending. Use this to confirm the server is wired up before touching Claude Desktop.
"""

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            info = (await session.initialize()).server_info
            print(f"connected: {info.name} v{info.version}\n")

            for tool in (await session.list_tools()).tools:
                first_line = (tool.description or "").strip().splitlines()[0]
                print(f"  {tool.name:16} {first_line}")

            print("\n--- system_status ---")
            result = await session.call_tool("system_status", {})
            print(result.content[0].text[:600])


if __name__ == "__main__":
    asyncio.run(main())
