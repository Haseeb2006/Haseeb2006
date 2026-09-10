"""The terminal side of a RED confirmation."""

from __future__ import annotations

import pytest
from mcp import types

from core import confirm


class FormParams:
    def __init__(self, message="Run the Shortcut 'Send Text'", schema=None):
        self.message = message
        self.requestedSchema = schema or {
            "type": "object",
            "properties": {"confirm": {"type": "boolean"}},
        }


class UrlParams:
    mode = "url"
    url = "https://example.com/approve"
    message = "Approve in your browser"


def _answer(monkeypatch, text):
    monkeypatch.setattr("builtins.input", lambda _prompt="": text)


@pytest.mark.parametrize("said", ["y", "Y", "yes", "  yes  "])
async def test_yes_accepts(monkeypatch, said):
    _answer(monkeypatch, said)
    result = await confirm.ask_terminal(None, FormParams())
    assert result.action == "accept"
    assert result.content == {"confirm": True}


@pytest.mark.parametrize("said", ["n", "no", "", "nope", "sure"])
async def test_anything_but_yes_declines(monkeypatch, said):
    """Silence is not consent: only an explicit yes runs a RED action."""
    _answer(monkeypatch, said)
    assert (await confirm.ask_terminal(None, FormParams())).action == "decline"


async def test_ctrl_d_cancels(monkeypatch):
    def raise_eof(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    assert (await confirm.ask_terminal(None, FormParams())).action == "cancel"


async def test_url_mode_is_refused_rather_than_guessed_at(monkeypatch):
    _answer(monkeypatch, "y")
    result = await confirm.ask_terminal(None, UrlParams())
    assert isinstance(result, types.ErrorData)


async def test_the_message_is_shown_to_the_user(monkeypatch, capsys):
    shown = {}
    monkeypatch.setattr("builtins.input", lambda prompt="": shown.setdefault("p", prompt) or "n")
    await confirm.ask_terminal(None, FormParams(message="Run 'Delete Everything'"))
    assert "Delete Everything" in shown["p"]


async def test_non_interactive_callback_denies(monkeypatch):
    assert (await confirm.deny_all(None, FormParams())).action == "decline"
