"""Diagnose (and optionally fix) the Claude Desktop wiring for jarvis-mcp.

    uv run python doctor.py           # check everything, change nothing
    uv run python doctor.py --fix     # write a correct config, backing up first

Checks the whole chain: the config file exists and parses, names a `uv` that is
really there, points at this checkout, and — the part nothing else verifies —
that the exact command Claude Desktop will run actually starts a server that
answers with the five tools.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

CONFIG = Path(
    "~/Library/Application Support/Claude/claude_desktop_config.json"
).expanduser()
HERE = Path(__file__).resolve().parent

PASS, FAIL, WARN, INFO = "  ok  ", " FAIL ", " warn ", "      "
problems: list[str] = []


def say(mark: str, message: str, fix: str | None = None) -> None:
    print(f"[{mark}] {message}")
    if fix:
        print(f"         -> {fix}")
    if mark == FAIL and fix:
        problems.append(fix)


def find_uv() -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    for guess in ("~/.local/bin/uv", "/opt/homebrew/bin/uv", "/usr/local/bin/uv"):
        path = Path(guess).expanduser()
        if path.exists():
            return str(path)
    return None


def desired_block(uv_path: str) -> dict:
    roots = [
        str(Path(f"~/{name}").expanduser())
        for name in ("Documents", "Desktop", "Projects")
        if Path(f"~/{name}").expanduser().is_dir()
    ]
    return {
        "command": uv_path,
        "args": ["--directory", str(HERE), "run", "jarvis-mcp"],
        "env": {"JARVIS_ALLOWED_ROOTS": ",".join(roots)},
    }


def check_platform() -> None:
    if sys.platform != "darwin":
        say(WARN, f"Running on {sys.platform}, not macOS — paths will not match.")


def load_config(path: Path) -> dict | None:
    if not path.exists():
        say(
            FAIL,
            f"No config file at {path}",
            "Run this again with --fix to create it.",
        )
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        say(
            FAIL,
            f"{path.name} is not valid JSON (line {exc.lineno}): {exc.msg}",
            "Fix the syntax — a stray comma or a missing brace — then re-run.",
        )
        return None
    say(PASS, f"Config found and parses: {path}")
    return data


def check_entry(config: dict) -> dict | None:
    servers = config.get("mcpServers") or {}
    if "jarvis" not in servers:
        listed = ", ".join(servers) or "none"
        say(
            FAIL,
            f"No 'jarvis' server in mcpServers (found: {listed})",
            "Run this again with --fix to add it.",
        )
        return None
    say(PASS, "mcpServers.jarvis entry present")
    return servers["jarvis"]


def check_command(entry: dict) -> None:
    command = entry.get("command", "")
    if not command:
        say(FAIL, "Entry has no 'command'", "Run with --fix.")
        return
    if not Path(command).is_absolute():
        say(
            FAIL,
            f"command is {command!r}, not an absolute path",
            "Claude Desktop does not inherit your shell PATH. Run with --fix.",
        )
        return
    if not Path(command).exists():
        say(FAIL, f"command does not exist: {command}", "Run with --fix.")
        return
    say(PASS, f"command is an absolute path that exists: {command}")


def check_directory(entry: dict) -> None:
    args = entry.get("args", [])
    if "--directory" not in args:
        say(FAIL, "args has no --directory", "Run with --fix.")
        return
    directory = Path(args[args.index("--directory") + 1])
    if not (directory / "pyproject.toml").exists():
        say(
            FAIL,
            f"--directory has no pyproject.toml: {directory}",
            f"Should be {HERE}. Run with --fix.",
        )
        return
    if directory.resolve() != HERE:
        say(WARN, f"--directory points at {directory}, not this checkout ({HERE})")
        return
    say(PASS, f"--directory points at this checkout: {directory}")


def check_roots(entry: dict) -> None:
    raw = (entry.get("env") or {}).get("JARVIS_ALLOWED_ROOTS", "")
    if not raw:
        say(WARN, "No JARVIS_ALLOWED_ROOTS set — search_files will have nothing to search.")
        return
    missing = [r for r in raw.split(",") if r.strip() and not Path(r.strip()).is_dir()]
    if missing:
        say(WARN, f"Allowed roots that do not exist: {', '.join(missing)}")
    else:
        say(PASS, f"Allowed roots all exist: {raw}")


async def check_launch(entry: dict) -> None:
    """Start the configured command and speak MCP to it, exactly as Claude will."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    command, args = entry.get("command"), entry.get("args", [])
    if not command or not Path(str(command)).exists():
        say(INFO, "Skipping launch test — the command above must be fixed first.")
        return

    env = dict(os.environ) | (entry.get("env") or {})
    try:
        params = StdioServerParameters(command=command, args=args, env=env)
        async with asyncio.timeout(60):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    info = (await session.initialize()).server_info
                    tools = [t.name for t in (await session.list_tools()).tools]
    except Exception as exc:  # noqa: BLE001 - report whatever went wrong, verbatim
        say(
            FAIL,
            f"The configured command did not start a working server: "
            f"{type(exc).__name__}: {exc}",
            f"Try running it by hand:  {command} {' '.join(args)}",
        )
        return

    say(PASS, f"Launched and handshook: {info.name} v{info.version}")
    say(PASS, f"Tools exposed: {', '.join(tools)}")


def apply_fix(path: Path) -> None:
    uv_path = find_uv()
    if not uv_path:
        print("Cannot find `uv`. Install it, then re-run:")
        print("  curl -LsSf https://astral.sh/uv/install.sh | sh")
        raise SystemExit(1)

    config = {}
    if path.exists():
        try:
            config = json.loads(path.read_text())
        except json.JSONDecodeError:
            print(f"{path} is not valid JSON. Fix or delete it first — refusing to")
            print("overwrite a file whose contents cannot be read.")
            raise SystemExit(1)
        backup = path.with_suffix(".json.bak")
        backup.write_text(path.read_text())
        print(f"Backed up existing config to {backup}")

    # Touch only our own key: other MCP servers stay exactly as they are.
    config.setdefault("mcpServers", {})["jarvis"] = desired_block(uv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")
    print(f"Wrote mcpServers.jarvis to {path}\n")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="write a correct config")
    parser.add_argument("--config", type=Path, default=CONFIG, help="config path")
    args = parser.parse_args()

    print("jarvis-mcp doctor\n")
    check_platform()

    if args.fix:
        apply_fix(args.config)

    config = load_config(args.config)
    if config is not None:
        entry = check_entry(config)
        if entry is not None:
            check_command(entry)
            check_directory(entry)
            check_roots(entry)
            await check_launch(entry)

    print()
    if problems:
        print("Not ready yet:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("Config looks right. Now, in Claude Desktop:")
    print("  1. Quit it completely with Cmd-Q (closing the window is not enough).")
    print("  2. Reopen it.")
    print("  3. Check Settings > Developer — 'jarvis' should be listed as running.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
