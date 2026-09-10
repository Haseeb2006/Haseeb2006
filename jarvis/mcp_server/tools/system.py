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
    "Connected to Wi-Fi, but the network name is hidden: since macOS 14 reading "
    "the SSID requires Location Services permission for the app running this "
    "server. Grant it in System Settings > Privacy & Security > Location Services."
)


def parse_boolean(output: str) -> bool | None:
    """AppleScript prints booleans as a bare `true` or `false`."""
    return {"true": True, "false": False}.get(output.strip().lower())


async def _muted() -> bool | None:
    result = await macos.osascript("output muted of (get volume settings)")
    return parse_boolean(result.stdout)


async def _dark_mode() -> bool | None:
    result = await macos.osascript(
        'tell application "System Events" to tell appearance preferences '
        "to get dark mode"
    )
    return parse_boolean(result.stdout)


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


def parse_ssid(airport_output: str) -> str | None:
    """The SSID named by `networksetup -getairportnetwork`, if it named one.

    A None here is NOT evidence of being offline. On macOS 14+ this command
    answers "You are not associated with an AirPort network." to any process
    without Location Services permission, whether or not Wi-Fi is connected — so
    it cannot tell "offline" apart from "not allowed to tell you". Whether the
    link is actually up is decided by `parse_link_active` instead.
    """
    text = airport_output.strip()
    # No trailing space in the marker: an empty SSID prints as "…Network: " and
    # stripping the output would otherwise stop the marker from matching at all.
    marker = "Current Wi-Fi Network:"
    if marker in text:
        return text.split(marker, 1)[1].strip() or None
    return None


def parse_link_active(ifconfig_output: str) -> bool:
    """Whether the interface is actually associated, per `ifconfig <device>`.

    This is the one signal here that no permission gates: the link is up or it
    is not, regardless of whether we are allowed to know the network's name.
    """
    return "status: active" in ifconfig_output


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
    ssid = parse_ssid(result.stdout)
    if ssid:
        return ssid, None

    # Second source for the name, which sometimes answers when networksetup will not.
    summary = await macos.run("ipconfig", "getsummary", device)
    ssid = parse_ssid_from_summary(summary.stdout)
    if ssid:
        return ssid, None

    # Neither would name the network. That is not the same as being offline, so
    # ask the link itself — the only signal here that no permission gates — and
    # report the reason it stayed nameless rather than inventing a verdict.
    link = await macos.run("ifconfig", device)
    if parse_link_active(link.stdout):
        return None, LOCATION_HINT
    return None, "Not connected to a Wi-Fi network."


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


async def set_volume(level: int) -> dict[str, Any]:
    """Set the Mac's output volume to a percentage from 0 to 100.

    Args:
        level: Volume percentage. 0 mutes.
    """
    macos.require_macos("set_volume")
    try:
        level = int(level)
    except (TypeError, ValueError):
        raise ValueError(f"level must be a whole number, got {level!r}") from None
    if not 0 <= level <= 100:
        raise ValueError(f"level must be between 0 and 100, got {level}")

    # This is the one place a value reaches an interpreter. `level` is an int in
    # a known range by the time it gets here, so there is no string to inject.
    previous = await macos.probe(_volume())
    result = await macos.osascript(f"set volume output volume {level}")
    if not result.ok:
        raise RuntimeError(result.stderr.strip() or "could not set the volume")
    return {"volume_percent": level, "previous_percent": previous}


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
        "muted": await macos.probe(_muted()),
        "dark_mode": await macos.probe(_dark_mode()),
        "muted": await macos.probe(_muted()),
        "dark_mode": await macos.probe(_dark_mode()),
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
