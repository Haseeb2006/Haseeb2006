"""Agent loop tests. No API key needed — the Anthropic client is faked."""

from __future__ import annotations

import anthropic
import httpx2 as httpx  # anthropic 1.x is built on httpx2
import pytest

from core import settings
from core.agent import Jarvis, build_system, volatile_context
from core.machine import Machine


class FakeMachine:
    claude_tools: list = []
    tool_names: list = []


class Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class Message:
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason


class FakeRunner:
    def __init__(self, turns, tool_result=None):
        self._turns = turns
        self._tool_result = tool_result

    def __aiter__(self):
        async def gen():
            for turn in self._turns:
                yield turn

        return gen()

    def generate_tool_call_response(self):
        return self._tool_result


class FakeMessages:
    def __init__(self, script, fail_with=None):
        self.script = list(script)
        self.calls: list[dict] = []
        self.fail_with = fail_with

    def tool_runner(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_with is not None:
            error, self.fail_with = self.fail_with, None
            raise error
        return self.script.pop(0)


class FakeClient:
    def __init__(self, script, fail_with=None):
        self.beta = type(
            "Beta", (), {"messages": FakeMessages(script, fail_with)}
        )()


def _bad_request(message):
    return anthropic.BadRequestError(
        message=message,
        response=httpx.Response(400, request=httpx.Request("POST", "https://api")),
        body=None,
    )


# --- prompt assembly: the caching contract ---


def test_cache_breakpoint_is_on_the_last_system_block_only():
    blocks = build_system()
    assert "cache_control" in blocks[-1]
    assert all("cache_control" not in b for b in blocks[:-1])


def test_system_prompt_holds_nothing_that_changes():
    """A varying byte in the system prompt invalidates the cache every request."""
    first = build_system()
    second = build_system()
    assert first == second
    joined = " ".join(b["text"] for b in first)
    assert volatile_context() not in joined


async def test_the_clock_travels_with_the_user_turn(monkeypatch):
    client = FakeClient([FakeRunner([Message([Block("text", text="hi")])])])
    jarvis = Jarvis(FakeMachine(), client=client)
    await jarvis.ask("hello")

    first_user = jarvis.messages[0]
    assert first_user["role"] == "user"
    assert first_user["content"][0]["text"] == volatile_context()
    assert first_user["content"][1]["text"] == "hello"


# --- the loop ---


async def test_reply_is_the_final_text():
    client = FakeClient([FakeRunner([Message([Block("text", text="Battery 100%.")])])])
    assert await Jarvis(FakeMachine(), client=client).ask("battery?") == "Battery 100%."


async def test_history_carries_across_turns():
    client = FakeClient(
        [
            FakeRunner([Message([Block("text", text="one")])]),
            FakeRunner([Message([Block("text", text="two")])]),
        ]
    )
    jarvis = Jarvis(FakeMachine(), client=client)
    await jarvis.ask("first")
    await jarvis.ask("second")

    roles = [m["role"] for m in jarvis.messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    # The second request was handed the first exchange, not a blank slate.
    assert len(client.beta.messages.calls[1]["messages"]) == 3


async def test_tool_results_are_mirrored_into_history():
    tool_turn = Message([Block("tool_use", name="system_status", input={})])
    final = Message([Block("text", text="100%.")])
    result = {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}
    client = FakeClient([FakeRunner([tool_turn, final], tool_result=result)])

    jarvis = Jarvis(FakeMachine(), client=client)
    await jarvis.ask("battery?")
    assert result in jarvis.messages


async def test_tool_calls_are_reported_as_they_happen():
    seen = []
    tool_turn = Message([Block("tool_use", name="open_app", input={"name": "Music"})])
    client = FakeClient([FakeRunner([tool_turn, Message([Block("text", text="done")])])])

    await Jarvis(FakeMachine(), client=client, on_tool=lambda n, a: seen.append((n, a))).ask("music")
    assert seen == [("open_app", {"name": "Music"})]


async def test_refusal_is_reported_plainly():
    client = FakeClient(
        [FakeRunner([Message([Block("text", text="")], stop_reason="refusal")])]
    )
    assert "can't help" in await Jarvis(FakeMachine(), client=client).ask("something")


# --- request shape ---


async def test_request_uses_adaptive_thinking_and_effort():
    client = FakeClient([FakeRunner([Message([Block("text", text="ok")])])])
    await Jarvis(FakeMachine(), client=client).ask("hi")
    call = client.beta.messages.calls[0]

    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"] == {"effort": settings.EFFORT}
    # budget_tokens is rejected outright on this model family.
    assert "budget_tokens" not in str(call)
    assert call["model"] == settings.MODEL


# --- failure handling ---


async def test_fallback_is_dropped_and_retried_when_the_account_lacks_it():
    client = FakeClient(
        [FakeRunner([Message([Block("text", text="recovered")])])],
        fail_with=_bad_request("fallbacks: beta not enabled for this organization"),
    )
    jarvis = Jarvis(FakeMachine(), client=client)
    assert await jarvis.ask("hi") == "recovered"
    # Second attempt carried neither the beta flag nor the parameter.
    retry = client.beta.messages.calls[1]
    assert "fallbacks" not in retry and "betas" not in retry


async def test_an_unrelated_bad_request_is_not_swallowed():
    client = FakeClient([], fail_with=_bad_request("max_tokens is too large"))
    with pytest.raises(anthropic.BadRequestError):
        await Jarvis(FakeMachine(), client=client).ask("hi")


async def test_a_failed_turn_leaves_no_dangling_tool_use():
    """The API rejects every later request if a tool_use has no result."""
    tool_turn = Message([Block("tool_use", name="system_status", input={})])
    client = FakeClient(
        [FakeRunner([Message([Block("text", text="fine")])])],
        fail_with=RuntimeError("connection dropped mid-turn"),
    )
    jarvis = Jarvis(FakeMachine(), client=client)
    jarvis.messages.append({"role": "user", "content": "earlier"})
    jarvis.messages.append({"role": "assistant", "content": [tool_turn]})
    before = list(jarvis.messages)

    with pytest.raises(RuntimeError):
        await jarvis.ask("battery?")

    assert jarvis.messages == before, "a failed turn must roll back whole"


# --- connecting to the real server ---


async def test_machine_discovers_the_servers_tools(sandbox):
    """Integration: launches the actual MCP server and converts what it exposes."""
    client = FakeClient([FakeRunner([Message([Block("text", text="ok")])])])
    async with Machine() as machine:
        jarvis = Jarvis(machine, client=client)
        assert len(jarvis.tool_names) == 16
        await jarvis.ask("hi")
        sent = client.beta.messages.calls[0]["tools"]
        assert len(sent) == 16
        # One breakpoint, on the last tool: it ends the whole tool prefix.
        marked = [t for t in sent if t.to_dict().get("cache_control")]
        assert len(marked) == 1
        assert marked[0].to_dict()["name"] == machine.tool_names[-1]
