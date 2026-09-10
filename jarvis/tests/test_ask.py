"""The one-shot and hotkey entry points."""

from __future__ import annotations

import pytest

from core import settings
from ui.ask import parse_dialog_text


@pytest.mark.parametrize(
    "output,expected",
    [
        ("text returned:volume 40, button returned:Ask", "volume 40"),
        ("button returned:Ask, text returned:hello", "hello"),
        # The typed text may contain a comma; the button marker ends it, not a comma.
        ("text returned:remind me, then sleep, button returned:Ask",
         "remind me, then sleep"),
        ("text returned:  spaced  , button returned:Ask", "spaced"),
        ("text returned:, button returned:Ask", None),
        ("button returned:Cancel", None),
        ("", None),
    ],
)
def test_reading_what_was_typed(output, expected):
    assert parse_dialog_text(output) == expected


# --- the env file launchd needs ---


def test_env_file_is_read(tmp_path, monkeypatch):
    path = tmp_path / "env"
    path.write_text(
        "# a comment\n\n"
        "ANTHROPIC_API_KEY=sk-ant-example\n"
        'JARVIS_EFFORT="high"\n'
        "JARVIS_ROOTS='/Users/x/Documents'\n"
        "not a setting\n"
    )
    monkeypatch.setenv("JARVIS_ENV_FILE", str(path))
    for key in ("ANTHROPIC_API_KEY", "JARVIS_EFFORT", "JARVIS_ROOTS"):
        monkeypatch.delenv(key, raising=False)

    loaded = settings.load_env_file()
    assert set(loaded) == {"ANTHROPIC_API_KEY", "JARVIS_EFFORT", "JARVIS_ROOTS"}
    import os
    assert os.environ["JARVIS_EFFORT"] == "high"       # quotes stripped
    assert os.environ["JARVIS_ROOTS"] == "/Users/x/Documents"


def test_the_shell_wins_over_the_file(tmp_path, monkeypatch):
    """Running by hand with an exported value must override the daemon's file."""
    path = tmp_path / "env"
    path.write_text("JARVIS_EFFORT=low\n")
    monkeypatch.setenv("JARVIS_ENV_FILE", str(path))
    monkeypatch.setenv("JARVIS_EFFORT", "max")

    assert "JARVIS_EFFORT" not in settings.load_env_file()
    import os
    assert os.environ["JARVIS_EFFORT"] == "max"


def test_a_missing_env_file_is_fine(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ENV_FILE", str(tmp_path / "nope"))
    assert settings.load_env_file() == []
