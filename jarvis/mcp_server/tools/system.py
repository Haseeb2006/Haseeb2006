"""GREEN — read-only machine state."""

from __future__ import annotations

import re
import shutil
import time
from typing import Any

from .. import macos

_BATTERY_RE = re.compile(r"(\d+)%;\s*([^;]+);")


async def _battery() -> dict[str, Any] | None:
    result = await macos.run("pmset", "-g", "batt")
    match = _BATTERY_RE.search(result.stdout)
    if not match:
        return None
    return {"percent": int(match.group(1)), "state": match.group(2).strip()}


async def _volume() -> int | None:
    result = await macos.osascript("output volume of (get volume settings)")
    text = result.text()
    return int(text) if text.isdigit() else None


async def _wifi() -> str | None:
    # `airport` was removed in Sonoma; networksetup still reports the SSID.
    result = await macos.run("networksetup", "-getairportnetwork", "en0")
    text = result.text()
    marker = "Current Wi-Fi Network: "
    if marker in text:
        return text.split(marker, 1)[1].strip()
    return None


async def _frontmost_app() -> str | None:
    result = await macos.osascript(
        'tell application "System Events" to get name of first application '
        "process whose frontmost is true"
    )
    return result.text() or None


def _disk() -> dict[str, Any]:
    usage = shutil.disk_usage("/")
    return {
        "free_gb": round(usage.free / 1_000_000_000, 1),
        "total_gb": round(usage.total / 1_000_000_000, 1),
        "percent_used": round(100 * usage.used / usage.total),
    }


async def _uptime() -> str | None:
    result = await macos.run("uptime")
    text = result.text()
    return text.split(",")[0].strip() if text else None


async def system_status() -> dict[str, Any]:
    """Report the machine's current state.

    Returns battery level and charging state, output volume, the connected Wi-Fi
    network, free disk space, uptime, and which application is in the foreground.

    Any individual reading that is unavailable (no battery, Wi-Fi off) comes back
    as null rather than failing the whole call.
    """
    macos.require_macos("system_status")
    return {
        "battery": await macos.probe(_battery()),
        "volume_percent": await macos.probe(_volume()),
        "wifi_network": await macos.probe(_wifi()),
        "disk": _disk(),
        "uptime": await macos.probe(_uptime()),
        "frontmost_app": await macos.probe(_frontmost_app()),
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
