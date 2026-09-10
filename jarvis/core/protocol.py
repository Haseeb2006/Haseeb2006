"""The line protocol between the daemon and its clients.

Newline-delimited JSON over a Unix socket. A Unix socket rather than a TCP port
because this process can read files, control apps and spend money: filesystem
permissions are the access control, and nothing is reachable from the network.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

MAX_LINE = 64 * 1024  # a request is a sentence, not a payload


def socket_path() -> Path:
    return Path(os.environ.get("JARVIS_SOCKET", "~/.jarvis/jarvis.sock")).expanduser()


def encode(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def decode(line: bytes) -> dict[str, Any]:
    if len(line) > MAX_LINE:
        raise ValueError(f"request too long ({len(line)} bytes)")
    try:
        payload = json.loads(line.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object")
    return payload


def request(text: str) -> bytes:
    return encode({"text": text})


def ok(text: str, tier: str, label: str | None = None) -> bytes:
    return encode({"ok": True, "text": text, "tier": tier, "label": label})


def error(message: str) -> bytes:
    return encode({"ok": False, "error": message})
