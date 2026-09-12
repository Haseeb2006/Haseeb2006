"""The resident daemon.

Holds one Machine, one local model and one Claude conversation open, so a
keystroke gets an answer instead of paying for a cold start every time.

Requests are handled one at a time. There is a single conversation and a single
machine, and two prompts racing to change the volume — or two halves of one
answer interleaved — is not a feature.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

from . import protocol, settings
from .agent import Jarvis
from .confirm import ask_dialog
from .dispatch import Dispatcher
from .local import LocalModel
from .machine import Machine

def idle_reset_seconds() -> int:
    return int(os.environ.get("JARVIS_IDLE_RESET", "1800"))


class Daemon:
    def __init__(self, dispatcher: Any = None, jarvis: Any = None) -> None:
        self._dispatcher = dispatcher
        self._jarvis = jarvis
        self._lock = asyncio.Lock()
        self._last_seen = 0.0

    async def handle_text(self, text: str) -> tuple[str, str, str | None]:
        async with self._lock:
            now = asyncio.get_running_loop().time()
            # A conversation resumed hours later is a new one. Without this the
            # context grows all day and yesterday's topic colours today's answer.
            if (
                self._jarvis is not None
                and self._last_seen
                and now - self._last_seen > idle_reset_seconds()
            ):
                self._jarvis.messages.clear()
            self._last_seen = now

            reply = await self._dispatcher.handle(text)
            return reply.text, reply.tier.name.lower(), reply.label

    async def serve_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                line = await reader.readline()
                if not line:
                    return
                try:
                    payload = protocol.decode(line)
                    text = str(payload.get("text", "")).strip()
                    if not text:
                        raise ValueError("no text in request")
                except ValueError as exc:
                    writer.write(protocol.error(str(exc)))
                    await writer.drain()
                    continue

                try:
                    answer, tier, label = await self.handle_text(text)
                    writer.write(protocol.ok(answer, tier, label))
                except Exception as exc:  # noqa: BLE001 - one bad turn must not
                    # take the daemon down; the next keystroke should still work.
                    writer.write(protocol.error(f"{type(exc).__name__}: {exc}"))
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            return
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()


async def _bind(daemon: Daemon) -> asyncio.AbstractServer:
    path = protocol.socket_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    if path.exists():
        # Either another daemon owns it, or a previous one died without cleaning
        # up. Probe before assuming, so we never displace a live daemon.
        try:
            _, writer = await asyncio.open_unix_connection(str(path))
            writer.close()
            raise RuntimeError(f"a daemon is already listening on {path}")
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            path.unlink(missing_ok=True)

    server = await asyncio.start_unix_server(daemon.serve_client, path=str(path))
    os.chmod(path, 0o600)  # only this user may talk to it
    return server


async def run() -> int:
    loaded = settings.load_env_file()
    if loaded:
        print(f"loaded from ~/.jarvis/env: {', '.join(loaded)}", flush=True)

    local = LocalModel()
    usable, reason = await local.status()

    async with Machine(elicitation_callback=ask_dialog) as machine:
        jarvis = Jarvis(machine) if settings.has_api_key() else None
        daemon = Daemon(
            Dispatcher(machine, local=local if usable else None, claude=jarvis),
            jarvis,
        )
        server = await _bind(daemon)

        print(f"jarvis daemon on {protocol.socket_path()}", flush=True)
        print(f"  tools:  {len(machine.tool_names)}", flush=True)
        print(f"  local:  {local.model if usable else 'off — ' + reason}", flush=True)
        print(
            f"  claude: {settings.model() if jarvis else 'off — no ANTHROPIC_API_KEY'}",
            flush=True,
        )

        async with server:
            await server.serve_forever()
    return 0


def main() -> None:
    try:
        raise SystemExit(asyncio.run(run()))
    except KeyboardInterrupt:
        protocol.socket_path().unlink(missing_ok=True)
        raise SystemExit(0)
