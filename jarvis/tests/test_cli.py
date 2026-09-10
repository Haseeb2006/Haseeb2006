"""CLI error handling: what the user actually sees when a turn fails."""

from __future__ import annotations

import anthropic
import httpx2 as httpx
import pytest

from ui import cli


def _error(cls, message, status=400):
    return cls(
        message=f"Error code: {status}",
        response=httpx.Response(
            status, request=httpx.Request("POST", "https://api.anthropic.com")
        ),
        body={"type": "error", "error": {"type": "invalid_request_error",
                                         "message": message}},
    )


CREDIT = "Your credit balance is too low to access the Anthropic API."


def test_the_human_sentence_is_pulled_out_of_the_json():
    assert cli.api_message(_error(anthropic.BadRequestError, CREDIT)) == CREDIT


def test_falls_back_when_there_is_no_structured_body():
    exc = anthropic.BadRequestError(
        message="something broke",
        response=httpx.Response(400, request=httpx.Request("POST", "https://api")),
        body=None,
    )
    assert "something broke" in cli.api_message(exc)


def test_a_billing_failure_ends_the_session():
    """It repeats identically every turn; looping just reprints the same wall."""
    exc = _error(anthropic.BadRequestError, CREDIT)
    hint = cli.fatal_hint(exc, cli.api_message(exc))
    assert hint and "Plans & Billing" in hint
    assert "nothing is wrong with jarvis" in hint.lower()


def test_a_bad_key_ends_the_session():
    exc = _error(anthropic.AuthenticationError, "invalid x-api-key", status=401)
    assert "ANTHROPIC_API_KEY" in cli.fatal_hint(exc, cli.api_message(exc))


def test_an_ordinary_error_keeps_the_session_alive():
    exc = _error(anthropic.BadRequestError, "max_tokens is too large")
    assert cli.fatal_hint(exc, cli.api_message(exc)) is None


@pytest.mark.parametrize("word", ["quit", "exit", "bye", "q", "/quit", "QUIT"])
def test_leaving_does_not_cost_an_api_call(word):
    assert word.lower() in cli.LEAVE


@pytest.mark.parametrize("word", ["quitting time", "exit the app please", "query"])
def test_ordinary_sentences_are_not_mistaken_for_quitting(word):
    assert word.lower() not in cli.LEAVE
