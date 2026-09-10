"""The local model: it must fail soft and refuse to guess about the machine."""

from __future__ import annotations

import httpx2 as httpx
import pytest

from core.local import ESCALATE, LocalModel


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


def fake_client(monkeypatch, *, post=None, get=None):
    class Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None):
            if isinstance(post, Exception):
                raise post
            return post

        async def get(self, url):
            if isinstance(get, Exception):
                raise get
            return get

    monkeypatch.setattr(httpx, "AsyncClient", Client)


def chat(content):
    return FakeResponse({"message": {"content": content}})


async def test_answers_are_passed_through(monkeypatch):
    fake_client(monkeypatch, post=chat("Paris."))
    assert await LocalModel().answer("capital of France") == "Paris."


@pytest.mark.parametrize("said", [ESCALATE, f"  {ESCALATE}  ", "escalate", "ESCALATE."])
async def test_escalation_reads_as_none(monkeypatch, said):
    fake_client(monkeypatch, post=chat(said))
    assert await LocalModel().answer("plan my week") is None


async def test_an_empty_answer_escalates(monkeypatch):
    fake_client(monkeypatch, post=chat("   "))
    assert await LocalModel().answer("anything") is None


async def test_ollama_being_down_escalates_rather_than_crashing(monkeypatch):
    """A local failure is never terminal — the tier above can still answer."""
    fake_client(monkeypatch, post=httpx.ConnectError("refused"))
    assert await LocalModel().answer("hello") is None


async def test_a_timeout_escalates(monkeypatch):
    fake_client(monkeypatch, post=TimeoutError("too slow"))
    assert await LocalModel().answer("hello") is None


async def test_status_explains_ollama_being_absent(monkeypatch):
    fake_client(monkeypatch, get=httpx.ConnectError("refused"))
    usable, why = await LocalModel().status()
    assert usable is False
    assert "brew install ollama" in why


async def test_status_explains_a_missing_model(monkeypatch):
    fake_client(monkeypatch, get=FakeResponse({"models": [{"name": "llama3:8b"}]}))
    usable, why = await LocalModel(model="qwen3:4b").status()
    assert usable is False
    assert "ollama pull qwen3:4b" in why


async def test_status_accepts_the_pulled_model(monkeypatch):
    fake_client(monkeypatch, get=FakeResponse({"models": [{"name": "qwen3:4b"}]}))
    usable, why = await LocalModel(model="qwen3:4b").status()
    assert usable is True and why == ""


async def test_a_bare_family_name_matches_its_tag(monkeypatch):
    fake_client(monkeypatch, get=FakeResponse({"models": [{"name": "qwen3:4b"}]}))
    usable, _ = await LocalModel(model="qwen3").status()
    assert usable is True
