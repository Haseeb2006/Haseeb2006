"""Tier selection: does each message reach the cheapest tier that can serve it."""

from __future__ import annotations

import pytest

from core.dispatch import Dispatcher, Reply, needs_machine
from core.machine import ToolFailed
from core.router import Tier


class FakeMachine:
    def __init__(self, results=None, fails=()):
        self.results = results or {}
        self.fails = set(fails)
        self.calls = []
        self.tool_names = ["system_status", "set_volume", "open_app", "set_mute"]
        self.claude_tools = []

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        if name in self.fails:
            raise ToolFailed(f"Could not open {arguments.get('name')!r}")
        return self.results.get(name, {})


class FakeLocal:
    def __init__(self, reply=None):
        self.reply = reply
        self.asked = []

    async def answer(self, text):
        self.asked.append(text)
        return self.reply


class FakeClaude:
    def __init__(self, reply="claude answered"):
        self.reply = reply
        self.asked = []

    async def ask(self, text):
        self.asked.append(text)
        return self.reply


# --- tier 0 ---


async def test_a_direct_command_never_reaches_a_model():
    machine = FakeMachine({"set_volume": {"volume_percent": 40}})
    local, claude = FakeLocal("nope"), FakeClaude()
    reply = await Dispatcher(machine, local, claude).handle("volume 40")

    assert reply.tier is Tier.DIRECT
    assert reply.text == "Volume set to 40%."
    assert machine.calls == [("set_volume", {"level": 40})]
    assert local.asked == [] and claude.asked == []


async def test_status_is_summarised_without_a_model():
    machine = FakeMachine({
        "system_status": {
            "battery": {"percent": 100, "state": "discharging"},
            "volume_percent": 81,
            "wifi_network": None,
            "disk": {"free_gb": 196.2},
            "frontmost_app": "Terminal",
            "notes": ["Connected to Wi-Fi, but the network name is hidden."],
        }
    })
    reply = await Dispatcher(machine, FakeLocal(), FakeClaude()).handle("battery")

    assert reply.tier is Tier.DIRECT
    assert "Battery 100% (discharging)" in reply.text
    assert "196.2GB free" in reply.text
    # A note explains an absent reading instead of silently dropping it.
    assert "hidden" in reply.text


async def test_a_tier_zero_miss_escalates_rather_than_erroring():
    """"open the pod bay doors" matches the words but not the world."""
    machine = FakeMachine(fails=["open_app"])
    claude = FakeClaude("That's not an app.")
    reply = await Dispatcher(machine, FakeLocal(), claude).handle("open the pod bay doors")

    assert machine.calls == [("open_app", {"name": "pod bay doors"})]
    assert reply.tier is Tier.CLAUDE
    assert claude.asked == ["open the pod bay doors"]


# --- tier 1 ---


async def test_general_questions_are_answered_locally():
    claude = FakeClaude()
    reply = await Dispatcher(FakeMachine(), FakeLocal("Paris."), claude).handle(
        "what is the capital of France"
    )
    assert reply.tier is Tier.LOCAL
    assert reply.text == "Paris."
    assert claude.asked == []


async def test_the_local_model_declining_escalates():
    claude = FakeClaude("something involved")
    reply = await Dispatcher(FakeMachine(), FakeLocal(None), claude).handle(
        "plan my week"
    )
    assert reply.tier is Tier.CLAUDE


@pytest.mark.parametrize(
    "said",
    [
        "summarise the files on my desktop",
        "why is my battery draining",
        "which app is using the network",
        "close the window",
    ],
)
async def test_machine_questions_skip_the_local_model(said):
    """A model with no tools would answer these from imagination."""
    local, claude = FakeLocal("I think your battery is fine!"), FakeClaude()
    reply = await Dispatcher(FakeMachine(), local, claude).handle(said)

    assert local.asked == [], "the local model must not guess about the machine"
    assert reply.tier is Tier.CLAUDE


def test_needs_machine_ignores_unrelated_words():
    assert not needs_machine("what is the capital of France")
    assert not needs_machine("explain recursion")
    assert needs_machine("what's on my desktop")


# --- no API key at all ---


async def test_without_claude_direct_commands_still_work():
    machine = FakeMachine({"set_volume": {"volume_percent": 20}})
    reply = await Dispatcher(machine, FakeLocal(), claude=None).handle("volume 20")
    assert reply.tier is Tier.DIRECT
    assert reply.text == "Volume set to 20%."


async def test_without_claude_the_local_model_still_answers():
    reply = await Dispatcher(FakeMachine(), FakeLocal("Paris."), claude=None).handle(
        "capital of France"
    )
    assert reply.tier is Tier.LOCAL


async def test_without_claude_an_escalation_says_so_plainly():
    reply = await Dispatcher(FakeMachine(), FakeLocal(None), claude=None).handle(
        "plan my week"
    )
    assert "ANTHROPIC_API_KEY" in reply.text
    assert "volume 40" in reply.text, "should suggest what does work"
    # No tier produced this, so it must not claim one did.
    assert reply.label == "unavailable"


async def test_with_nothing_but_rules_direct_commands_still_work():
    machine = FakeMachine({"system_status": {"battery": {"percent": 50, "state": "ok"}}})
    reply = await Dispatcher(machine, local=None, claude=None).handle("battery")
    assert reply.tier is Tier.DIRECT
    assert "50%" in reply.text


async def test_server_logs_do_not_land_in_the_users_prompt(tmp_path, monkeypatch):
    """The server logs to stderr, which the client inherits — keep it out of the UI."""
    from core.machine import Machine

    monkeypatch.setenv("JARVIS_ALLOWED_ROOTS", str(tmp_path))
    log = tmp_path / "server.log"
    with open(log, "w", encoding="utf-8") as handle:
        async with Machine(errlog=handle) as machine:
            with pytest.raises(Exception):
                await machine.call("system_status", {})
    # Whatever the server said about it went to the log, not the terminal.
    assert log.exists()


def test_memory_counts_read_as_english():
    from core.dispatch import _summarise

    one = _summarise("list_memories", {}, {"counts": {"fact": 1},
                                           "memories": [{"id": 1, "text": "x"}]})
    many = _summarise("list_memories", {}, {"counts": {"fact": 3},
                                            "memories": [{"id": 1, "text": "x"}]})
    assert one.startswith("1 fact:")
    assert many.startswith("3 facts:")
