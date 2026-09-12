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


# --- settings must be readable after the environment changes ---


def test_settings_follow_the_environment_not_the_import(monkeypatch):
    """The daemon loads ~/.jarvis/env after its imports.

    Regression: these were module constants captured at import time, so every
    setting in that file was silently ignored by a launchd-started daemon —
    which is the only way launchd has to configure one.
    """
    from core import local, settings
    from mcp_server import embeddings

    monkeypatch.setenv("JARVIS_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("JARVIS_EFFORT", "max")
    monkeypatch.setenv("JARVIS_MAX_ITERATIONS", "3")
    monkeypatch.setenv("OLLAMA_HOST", "http://elsewhere:9999/")
    monkeypatch.setenv("JARVIS_LOCAL_MODEL", "llama3.2:1b")
    monkeypatch.setenv("JARVIS_EMBED_MODEL", "mxbai-embed-large")

    assert settings.model() == "claude-sonnet-5"
    assert settings.effort() == "max"
    assert settings.max_iterations() == 3
    assert local.default_host() == "http://elsewhere:9999"   # trailing slash trimmed
    assert local.LocalModel().model == "llama3.2:1b"
    assert local.LocalModel().host == "http://elsewhere:9999"
    assert embeddings.model() == "mxbai-embed-large"
    assert embeddings.host() == "http://elsewhere:9999"


def test_an_env_file_setting_reaches_the_local_model(tmp_path, monkeypatch):
    """The end-to-end version of the same bug, through the file launchd uses."""
    from core import local, settings

    path = tmp_path / "env"
    path.write_text("JARVIS_LOCAL_MODEL=llama3.2:1b\nOLLAMA_HOST=http://box:1234\n")
    monkeypatch.setenv("JARVIS_ENV_FILE", str(path))
    monkeypatch.delenv("JARVIS_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    settings.load_env_file()
    assert local.LocalModel().model == "llama3.2:1b"
    assert local.LocalModel().host == "http://box:1234"
