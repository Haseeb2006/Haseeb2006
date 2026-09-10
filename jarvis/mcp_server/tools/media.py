"""Playback control for Apple Music.

`tell application "Music"` will *launch* Music if it is not running, so every
action that only makes sense for a running player checks first. Being told
"Music isn't playing" is better than having Music open itself to answer.
"""

from __future__ import annotations

from typing import Any

from .. import macos

APP = "Music"
SEPARATOR = "␟"  # a character no track title will contain

ACTIONS = {
    "play": "play",
    "pause": "pause",
    "playpause": "playpause",
    "next": "next track",
    "previous": "previous track",
}

# Only `play` is worth launching the app for; the rest are meaningless if it is
# not already running.
LAUNCHES = {"play", "playpause"}


async def _is_running() -> bool:
    result = await macos.osascript_argv(
        [
            'tell application "System Events" to return (exists (application '
            "process whose name is (item 1 of argv)))",
        ],
        APP,
    )
    return result.text().strip().lower() == "true"


def parse_track(output: str) -> dict[str, Any] | None:
    """Read the track line Music returns, or None if nothing is playing."""
    text = output.strip()
    if not text or SEPARATOR not in text:
        return None
    state, name, artist, album = (text.split(SEPARATOR) + ["", "", ""])[:4]
    if not name:
        return None
    return {
        "state": state or "unknown",
        "track": name,
        "artist": artist or None,
        "album": album or None,
    }


async def media_control(action: str) -> dict[str, Any]:
    """Control Apple Music playback.

    Args:
        action: One of play, pause, playpause, next, previous.
    """
    macos.require_macos("media_control")
    action = (action or "").strip().lower()
    if action not in ACTIONS:
        raise ValueError(
            f"action must be one of {', '.join(sorted(ACTIONS))}, got {action!r}"
        )

    if action not in LAUNCHES and not await _is_running():
        return {"action": action, "applied": False, "note": f"{APP} is not running."}

    result = await macos.osascript(f'tell application "{APP}" to {ACTIONS[action]}')
    if not result.ok:
        raise RuntimeError(result.stderr.strip() or f"could not {action}")
    return {"action": action, "applied": True}


async def now_playing() -> dict[str, Any]:
    """What Apple Music is currently playing, if anything."""
    macos.require_macos("now_playing")
    if not await _is_running():
        return {"playing": False, "note": f"{APP} is not running."}

    result = await macos.osascript(
        f'tell application "{APP}"\n'
        "  if player state is stopped then return \"\"\n"
        f'  return (player state as text) & "{SEPARATOR}" & (name of current track)'
        f' & "{SEPARATOR}" & (artist of current track) & "{SEPARATOR}"'
        " & (album of current track)\n"
        "end tell"
    )
    track = parse_track(result.stdout)
    if track is None:
        return {"playing": False, "note": f"Nothing is playing in {APP}."}
    return {"playing": track["state"] == "playing", **track}
