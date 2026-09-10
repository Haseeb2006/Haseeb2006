"""Paired controls: both directions, and the ones that only go one way."""

from __future__ import annotations

import pytest

from mcp_server import macos
from mcp_server.tools import controls, media


def fake_osascript(monkeypatch, capture, output="", ok=True):
    async def run(script, timeout=macos.DEFAULT_TIMEOUT):
        capture.append(script)
        return macos.Completed(0 if ok else 1, output, "" if ok else "failed")

    monkeypatch.setattr(macos, "is_macos", lambda: True)
    monkeypatch.setattr(macos, "osascript", run)


# --- volume, relative ---


async def test_louder_reads_then_clamps(monkeypatch):
    scripts = []
    fake_osascript(monkeypatch, scripts)
    monkeypatch.setattr(controls, "_volume", lambda: _value(95))

    result = await controls.change_volume(delta=10)
    # Clamped in Python, so the reported number is the one that was set.
    assert result == {"volume_percent": 100, "previous_percent": 95}
    assert "set volume output volume 100" in scripts[-1]


async def test_quieter_cannot_go_below_zero(monkeypatch):
    scripts = []
    fake_osascript(monkeypatch, scripts)
    monkeypatch.setattr(controls, "_volume", lambda: _value(5))
    assert (await controls.change_volume(delta=-10))["volume_percent"] == 0


async def test_change_volume_rejects_nonsense(monkeypatch):
    monkeypatch.setattr(macos, "is_macos", lambda: True)
    with pytest.raises(ValueError):
        await controls.change_volume(delta="loads")


def _value(number):
    async def coro():
        return number

    return coro()


# --- toggles: both directions ---


@pytest.mark.parametrize("muted,expected", [(True, "true"), (False, "false")])
async def test_mute_and_unmute(monkeypatch, muted, expected):
    scripts = []
    fake_osascript(monkeypatch, scripts)
    monkeypatch.setattr(controls, "_volume", lambda: _value(40))
    result = await controls.set_mute(muted=muted)
    assert result["muted"] is muted
    assert f"set volume output muted {expected}" in scripts[0]


@pytest.mark.parametrize("on,expected", [(True, "true"), (False, "false")])
async def test_dark_mode_both_ways(monkeypatch, on, expected):
    scripts = []
    fake_osascript(monkeypatch, scripts)
    assert (await controls.set_dark_mode(on=on))["dark_mode"] is on
    assert f"set dark mode to {expected}" in scripts[0]


@pytest.mark.parametrize("on,word", [(True, "on"), (False, "off")])
async def test_wifi_both_ways(monkeypatch, on, word):
    calls = []

    async def run(*argv, **kwargs):
        calls.append(argv)
        if argv[1] == "-listallhardwareports":
            return macos.Completed(0, "Hardware Port: Wi-Fi\nDevice: en0\n", "")
        return macos.Completed(0, "", "")

    monkeypatch.setattr(macos, "is_macos", lambda: True)
    monkeypatch.setattr(macos, "run", run)

    result = await controls.set_wifi(on=on)
    assert result == {"wifi_on": on, "interface": "en0"}
    # The interface is looked up, not assumed to be en0.
    assert calls[-1] == ("networksetup", "-setairportpower", "en0", word)


# --- clipboard: read and write ---


async def test_clipboard_round_trip(monkeypatch):
    written = {}

    async def run(*argv, **kwargs):
        if argv[0] == "pbcopy":
            written["text"] = kwargs.get("stdin")
            return macos.Completed(0, "", "")
        return macos.Completed(0, "hello there", "")

    monkeypatch.setattr(macos, "is_macos", lambda: True)
    monkeypatch.setattr(macos, "run", run)

    await controls.write_clipboard(text="hello there")
    # Clipboard text goes on stdin: it can be any size and contain anything.
    assert written["text"] == b"hello there"
    assert (await controls.read_clipboard())["text"] == "hello there"


async def test_empty_clipboard_is_flagged(monkeypatch):
    async def run(*argv, **kwargs):
        return macos.Completed(0, "   \n", "")

    monkeypatch.setattr(macos, "is_macos", lambda: True)
    monkeypatch.setattr(macos, "run", run)
    assert (await controls.read_clipboard())["empty"] is True


# --- media ---


def _music(monkeypatch, *, running, output=""):
    async def argv(lines, *args, **kwargs):
        return macos.Completed(0, "true" if running else "false", "")

    scripts = []

    async def script(text, timeout=macos.DEFAULT_TIMEOUT):
        scripts.append(text)
        return macos.Completed(0, output, "")

    monkeypatch.setattr(macos, "is_macos", lambda: True)
    monkeypatch.setattr(macos, "osascript_argv", argv)
    monkeypatch.setattr(macos, "osascript", script)
    return scripts


@pytest.mark.parametrize("action", ["pause", "next", "previous"])
async def test_control_does_not_launch_music_to_control_it(monkeypatch, action):
    """Pausing a player that is not running must not open it."""
    scripts = _music(monkeypatch, running=False)
    result = await media.media_control(action=action)
    assert result["applied"] is False
    assert scripts == [], "no AppleScript should have run"


async def test_play_may_launch_music(monkeypatch):
    scripts = _music(monkeypatch, running=False)
    assert (await media.media_control(action="play"))["applied"] is True
    assert scripts, "play is worth launching the app for"


async def test_unknown_action_is_rejected(monkeypatch):
    _music(monkeypatch, running=True)
    with pytest.raises(ValueError, match="action must be one of"):
        await media.media_control(action="rewind")


async def test_now_playing_when_stopped(monkeypatch):
    _music(monkeypatch, running=True, output="")
    assert (await media.now_playing())["playing"] is False


async def test_now_playing_when_music_is_closed(monkeypatch):
    _music(monkeypatch, running=False)
    result = await media.now_playing()
    assert result["playing"] is False
    assert "not running" in result["note"]


async def test_now_playing_reports_the_track(monkeypatch):
    line = f"playing{media.SEPARATOR}Alright{media.SEPARATOR}Kendrick Lamar{media.SEPARATOR}TPAB"
    _music(monkeypatch, running=True, output=line)
    result = await media.now_playing()
    assert result["track"] == "Alright" and result["artist"] == "Kendrick Lamar"
    assert result["playing"] is True


# --- one-way by nature ---


async def test_lock_screen_has_no_inverse(monkeypatch):
    calls = []

    async def run(*argv, **kwargs):
        calls.append(argv)
        return macos.Completed(0, "", "")

    monkeypatch.setattr(macos, "is_macos", lambda: True)
    monkeypatch.setattr(macos, "run", run)

    assert (await controls.lock_screen())["locked"] is True
    assert not hasattr(controls, "unlock_screen"), "unlocking needs a password"
