"""Append-only audit log.

Every tool call lands here — allowed, refused, or failed. Retrofitting this later
is miserable, so it exists from the first commit.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from . import config


def _redact(value: Any) -> Any:
    """Trim oversized argument values so the log stays greppable."""
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + f"…<{len(value) - 500} more chars>"
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value[:20]]
    return value


def record(
    *,
    tool: str,
    tier: str,
    outcome: str,
    arguments: dict[str, Any] | None = None,
    detail: str | None = None,
) -> None:
    """Append one entry. Never raises — a broken log must not break a tool."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": tool,
        "tier": tier,
        "outcome": outcome,
        "arguments": _redact(arguments or {}),
    }
    if detail:
        entry["detail"] = _redact(detail)

    try:
        path = config.audit_log_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Open with 0600 so the log is not world-readable on first creation.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
