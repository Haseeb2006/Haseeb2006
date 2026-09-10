"""Install (or remove) the launchd agent that keeps the daemon running.

    uv run python install_agent.py            # install and start
    uv run python install_agent.py --status
    uv run python install_agent.py --uninstall

launchd does not inherit your shell environment, so nothing exported in .zshrc
reaches the daemon. Keys and settings are read from ~/.jarvis/env instead — one
KEY=value per line — which this writes a template for.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

LABEL = "com.haseeb.jarvis"
BIN = Path("~/.local/bin").expanduser()
SHIMS = ("jarvis-ask", "jarvis-prompt", "jarvis")
HERE = Path(__file__).resolve().parent
AGENTS = Path("~/Library/LaunchAgents").expanduser()
PLIST = AGENTS / f"{LABEL}.plist"
ENV_FILE = Path("~/.jarvis/env").expanduser()
LOG_DIR = Path("~/.jarvis").expanduser()

ENV_TEMPLATE = """# Read by the jarvis daemon at startup, one KEY=value per line.
# launchd does not inherit your shell environment, so put settings here.
# Lines starting with # are ignored.

# ANTHROPIC_API_KEY=sk-ant-...
# JARVIS_EFFORT=low
# JARVIS_ALLOWED_ROOTS=/Users/YOU/Documents,/Users/YOU/Desktop
# JARVIS_ALLOWED_SHORTCUTS=
"""


def find_uv() -> str:
    found = shutil.which("uv")
    if found:
        return found
    for guess in ("~/.local/bin/uv", "/opt/homebrew/bin/uv", "/usr/local/bin/uv"):
        path = Path(guess).expanduser()
        if path.exists():
            return str(path)
    print("Could not find uv. Install it, then re-run:")
    print("  curl -LsSf https://astral.sh/uv/install.sh | sh")
    raise SystemExit(1)


def plist_contents(uv_path: str) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [uv_path, "--directory", str(HERE), "run", "jarvisd"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "WorkingDirectory": str(HERE),
        "StandardOutPath": str(LOG_DIR / "daemon.log"),
        "StandardErrorPath": str(LOG_DIR / "daemon.err"),
        "ProcessType": "Interactive",
    }


def link_commands() -> None:
    """Put jarvis-ask and friends on PATH.

    The console scripts live in the project's .venv, which is not on anyone's
    PATH, so `jarvis-ask battery` fails with command-not-found until something
    like this exists. A wrapper rather than a symlink, so it keeps working if
    the venv is rebuilt somewhere else.
    """
    BIN.mkdir(parents=True, exist_ok=True)
    venv = HERE / ".venv" / "bin"

    for name in SHIMS:
        target = venv / name
        if not target.exists():
            continue
        shim = BIN / name
        shim.write_text(f'#!/bin/sh\nexec "{target}" "$@"\n')
        shim.chmod(0o755)
    print(f"Linked {', '.join(SHIMS)} into {BIN}")

    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    if str(BIN) not in path_entries:
        print(f"\n  {BIN} is not on your PATH. Add it:")
        print(f'    echo \'export PATH="$HOME/.local/bin:$PATH"\' >> ~/.zshrc')
        print("    exec $SHELL")


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def domain() -> str:
    return f"gui/{os.getuid()}"


def install() -> int:
    uv_path = find_uv()
    LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    AGENTS.mkdir(parents=True, exist_ok=True)

    if not ENV_FILE.exists():
        ENV_FILE.write_text(ENV_TEMPLATE)
        os.chmod(ENV_FILE, 0o600)  # it will hold an API key
        print(f"Wrote {ENV_FILE} — put your ANTHROPIC_API_KEY there.")
    else:
        print(f"Keeping your existing {ENV_FILE}")

    with open(PLIST, "wb") as handle:
        plistlib.dump(plist_contents(uv_path), handle)
    print(f"Wrote {PLIST}")

    # bootout first so a re-install replaces the running agent rather than
    # failing with "service already loaded".
    _launchctl("bootout", f"{domain()}/{LABEL}")
    result = _launchctl("bootstrap", domain(), str(PLIST))
    if result.returncode != 0:
        print(f"launchctl bootstrap failed: {result.stderr.strip()}")
        return 1
    _launchctl("kickstart", f"{domain()}/{LABEL}")

    link_commands()

    print("\nStarted. Check it with:")
    print("  uv run python install_agent.py --status")
    print("  uv run jarvis-ask battery")
    return 0


def uninstall() -> int:
    result = _launchctl("bootout", f"{domain()}/{LABEL}")
    PLIST.unlink(missing_ok=True)
    print(f"Removed {PLIST}")
    if result.returncode != 0 and "No such process" not in result.stderr:
        print(f"({result.stderr.strip()})")
    print(f"Left {ENV_FILE} and ~/.jarvis alone — your memories live there.")
    return 0


def status() -> int:
    from core import protocol

    print(f"plist:  {'present' if PLIST.exists() else 'not installed'}  {PLIST}")
    result = _launchctl("print", f"{domain()}/{LABEL}")
    if result.returncode != 0:
        print("agent:  not loaded")
    else:
        state = [line.strip() for line in result.stdout.splitlines()
                 if line.strip().startswith(("state =", "pid ="))]
        print(f"agent:  loaded ({'; '.join(state) or 'running'})")

    socket = protocol.socket_path()
    print(f"socket: {'present' if socket.exists() else 'absent'}  {socket}")
    linked = [name for name in SHIMS if (BIN / name).exists()]
    print(f"onpath: {', '.join(linked) if linked else 'none — run with --link'}")
    if linked and str(BIN) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"        (but {BIN} is not on your PATH)")

    for log in (LOG_DIR / "daemon.log", LOG_DIR / "daemon.err"):
        if log.exists() and log.stat().st_size:
            print(f"\n--- {log.name} (last lines) ---")
            print("\n".join(log.read_text(errors="replace").splitlines()[-8:]))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--link", action="store_true",
                        help="only put the commands on PATH, without touching launchd")
    args = parser.parse_args()

    # Linking is just files on PATH; only the launchd parts are macOS-only.
    if args.link:
        link_commands()
        return 0
    if sys.platform != "darwin":
        print("launchd is macOS-only.")
        return 1
    if args.uninstall:
        return uninstall()
    if args.status:
        return status()
    return install()


if __name__ == "__main__":
    raise SystemExit(main())
