"""Machine controls that come in pairs: on/off, up/down, read/write.

Every toggle here takes a boolean rather than having separate on and off tools.
One tool with a state is harder to half-implement than two that can drift, and
the model picks the direction from one obvious argument.
"""

from __future__ import annotations

from typing import Any

from .. import macos
from .system import _volume, parse_wifi_device

STEP = 10  # what "louder" means, in percent


async def change_volume(delta: int) -> dict[str, Any]:
    """Raise or lower the output volume by a number of percentage points.

    Args:
        delta: Points to change by. Positive is louder, negative is quieter.
    """
    macos.require_macos("change_volume")
    try:
        delta = int(delta)
    except (TypeError, ValueError):
        raise ValueError(f"delta must be a whole number, got {delta!r}") from None

    current = await _volume()
    if current is None:
        raise RuntimeError("Could not read the current volume.")

    # Clamped here rather than in AppleScript, so the reported result is the
    # value that was actually set.
    level = max(0, min(100, current + delta))
    result = await macos.osascript(f"set volume output volume {level}")
    if not result.ok:
        raise RuntimeError(result.stderr.strip() or "could not change the volume")
    return {"volume_percent": level, "previous_percent": current}


async def set_mute(muted: bool) -> dict[str, Any]:
    """Mute or unmute the output.

    Unmuting restores the previous level, which is why this is separate from
    setting the volume to zero.

    Args:
        muted: True to mute, False to unmute.
    """
    macos.require_macos("set_mute")
    flag = "true" if muted else "false"
    result = await macos.osascript(f"set volume output muted {flag}")
    if not result.ok:
        raise RuntimeError(result.stderr.strip() or "could not change mute state")
    return {"muted": bool(muted), "volume_percent": await macos.probe(_volume())}


async def set_wifi(on: bool) -> dict[str, Any]:
    """Turn Wi-Fi on or off.

    Args:
        on: True to turn Wi-Fi on, False to turn it off.
    """
    macos.require_macos("set_wifi")
    ports = await macos.run("networksetup", "-listallhardwareports")
    device = parse_wifi_device(ports.stdout)
    if device is None:
        raise RuntimeError("No Wi-Fi interface found on this Mac.")

    result = await macos.run(
        "networksetup", "-setairportpower", device, "on" if on else "off"
    )
    if not result.ok:
        raise RuntimeError(result.stderr.strip() or "could not change Wi-Fi power")
    return {"wifi_on": bool(on), "interface": device}


async def set_dark_mode(on: bool) -> dict[str, Any]:
    """Turn the system's dark appearance on or off.

    Args:
        on: True for dark mode, False for light mode.
    """
    macos.require_macos("set_dark_mode")
    flag = "true" if on else "false"
    result = await macos.osascript(
        "tell application \"System Events\" to tell appearance preferences "
        f"to set dark mode to {flag}"
    )
    if not result.ok:
        detail = result.stderr.strip()
        raise RuntimeError(
            f"Could not change appearance: {detail}"
            if detail else
            "Could not change appearance. This server may need Automation "
            "permission for System Events in System Settings > Privacy & Security."
        )
    return {"dark_mode": bool(on)}


async def read_clipboard() -> dict[str, Any]:
    """Read whatever text is currently on the clipboard."""
    macos.require_macos("read_clipboard")
    result = await macos.run("pbpaste")
    text = result.stdout
    return {
        "text": text,
        "length": len(text),
        "empty": not text.strip(),
    }


async def write_clipboard(text: str) -> dict[str, Any]:
    """Put text on the clipboard, replacing what was there.

    Args:
        text: The text to copy.
    """
    macos.require_macos("write_clipboard")
    # Passed on stdin, never as an argument: clipboard contents can be any size
    # and contain anything at all.
    result = await macos.run("pbcopy", stdin=text.encode("utf-8"))
    if not result.ok:
        raise RuntimeError(result.stderr.strip() or "could not write the clipboard")
    return {"copied": True, "length": len(text)}


async def lock_screen() -> dict[str, Any]:
    """Lock the screen immediately.

    There is no unlock: that needs the user's password, by design.
    """
    macos.require_macos("lock_screen")
    result = await macos.run("open", "-a", "ScreenSaverEngine")
    if not result.ok:
        raise RuntimeError(result.stderr.strip() or "could not lock the screen")
    return {"locked": True}
