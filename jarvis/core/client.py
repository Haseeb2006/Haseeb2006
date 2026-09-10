"""Talking to the daemon, and coping when it is not there."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from . import protocol


class NoDaemon(Exception):
    """Nothing is listening on the socket."""


@dataclass
class Answer:
    text: str
    tier: str = ""
    label: str | None = None

    @property
    def mark(self) -> str:
        return self.label or self.tier


async def ask(text: str, timeout: float = 180.0) -> Answer:
    """Send one message to the daemon and wait for its reply."""
    path = protocol.socket_path()
    try:
        reader, writer = await asyncio.open_unix_connection(str(path))
    except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
        raise NoDaemon(f"No daemon listening on {path}") from exc

    try:
        writer.write(protocol.request(text))
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionResetError, BrokenPipeError):
            pass

    if not line:
        raise NoDaemon("The daemon closed the connection without answering")

    payload = protocol.decode(line)
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error", "the daemon reported an error"))
    return Answer(payload.get("text", ""), payload.get("tier", ""), payload.get("label"))
