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


LOCATION_HINT = (
    "Wi-Fi network name is hidden: since macOS 14, reading the SSID requires "
    "Location Services permission for the app running this server. Grant it in "
    "System Settings > Privacy & Security > Location Services."
)


def parse_wifi_device(hardware_ports: str) -> str | None:
    """Find the Wi-Fi interface in `networksetup -listallhardwareports` output.

    Wi-Fi is en0 on most Apple silicon Macs and en1 on many Intel ones, so the
    interface is looked up rather than assumed.
    """
    lines = hardware_ports.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("Hardware Port:"):
            continue
        port = line.split(":", 1)[1].strip()
        if port not in ("Wi-Fi", "AirPort"):
            continue
        for follow in lines[index + 1 : index + 3]:
            if follow.startswith("Device:"):
                return follow.split(":", 1)[1].strip()
    return None


def parse_ssid(airport_output: str) -> tuple[str | None, str | None]:
    """Read `networksetup -getairportnetwork` output as (ssid, reason_it_is_absent)."""
    text = airport_output.strip()
    # No trailing space in the marker: an empty SSID prints as "…Network: " and
    # stripping the output would otherwise stop the marker from matching at all.
    marker = "Current Wi-Fi Network:"
    if marker in text:
        ssid = text.split(marker, 1)[1].strip()
        return (ssid, None) if ssid else (None, LOCATION_HINT)
    if "not associated" in text.lower():
        return None, "Not connected to a Wi-Fi network."
    return None, None


def parse_ssid_from_summary(summary: str) -> str | None:
    """Pull the SSID out of `ipconfig getsummary <dev>`, which formats it as
    `  SSID : MyNetwork` — a second source when networksetup declines to say."""
    for line in summary.splitlines():
        stripped = line.strip()
        if stripped.startswith("SSID :"):
            ssid = stripped.split(":", 1)[1].strip()
            if ssid and ssid != "<redacted>":
                return ssid
    return None


async def _wifi() -> tuple[str | None, str | None]:
    """Return (network name, reason it is unavailable). `airport` is gone in Sonoma."""
    ports = await macos.run("networksetup", "-listallhardwareports")
    device = parse_wifi_device(ports.stdout)
    if device is None:
        return None, "No Wi-Fi interface found on this Mac."

    result = await macos.run("networksetup", "-getairportnetwork", device)
    ssid, reason = parse_ssid(result.stdout)
    if ssid:
        return ssid, None

    # networksetup did not name a network. Ask the interface itself before
    # concluding anything — it is the ground truth, and networksetup reports
    # "not associated" in cases where the interface does hold an SSID. Reporting
    # "not connected" when you are connected is worse than reporting nothing.
    summary = await macos.run("ipconfig", "getsummary", device)
    ssid = parse_ssid_from_summary(summary.stdout)
    if ssid:
        return ssid, None
    return None, reason or LOCATION_HINT


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
    wifi = await macos.probe(_wifi()) or (None, None)
    ssid, wifi_reason = wifi

    status: dict[str, Any] = {
        "battery": await macos.probe(_battery()),
        "volume_percent": await macos.probe(_volume()),
        "wifi_network": ssid,
        "disk": _disk(),
        "uptime": await macos.probe(_uptime()),
        "frontmost_app": await macos.probe(_frontmost_app()),
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # A null reading with no explanation invites the model to guess. Say why.
    notes = [wifi_reason] if wifi_reason else []
    if status["frontmost_app"] is None:
        notes.append(
            "Frontmost app is unavailable: this server needs Accessibility "
            "permission in System Settings > Privacy & Security > Accessibility."
        )
    if notes:
        status["notes"] = notes
    return status
