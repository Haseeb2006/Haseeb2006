"""The daemon and its socket protocol, exercised over a real Unix socket."""

from __future__ import annotations

import asyncio
import os
import stat

import pytest

from core import client, protocol
from core.daemon import Daemon, _bind
from core.dispatch import Reply
from core.router import Tier


class FakeDispatcher:
    def __init__(self, reply=None, error=None):
        self.reply = reply or Reply("done", Tier.DIRECT)
        self.error = error
        self.seen = []

    async def handle(self, text):
        self.seen.append(text)
        if self.error:
            raise self.error
        if callable(self.reply):
            return await self.reply(text)
        return self.reply


class FakeJarvis:
    def __init__(self):
        self.messages = [{"role": "user", "content": "old"}]


@pytest.fixture
def socket_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_SOCKET", str(tmp_path / "jarvis.sock"))
    return tmp_path


async def serving(daemon):
    server = await _bind(daemon)
    return server


# --- protocol ---


def test_round_trip():
    payload = protocol.decode(protocol.request("volume 40"))
    assert payload == {"text": "volume 40"}


def test_oversized_requests_are_refused():
    with pytest.raises(ValueError, match="too long"):
        protocol.decode(b"x" * (protocol.MAX_LINE + 1))


@pytest.mark.parametrize("junk", [b"not json\n", b'"a string"\n', b"[1,2]\n"])
def test_malformed_requests_are_refused(junk):
    with pytest.raises(ValueError):
        protocol.decode(junk)


# --- the socket ---


async def test_ask_and_answer(socket_dir):
    dispatcher = FakeDispatcher(Reply("Volume set to 40%.", Tier.DIRECT, "set_volume"))
    server = await serving(Daemon(dispatcher))
    async with server:
        answer = await client.ask("volume 40")
    assert answer.text == "Volume set to 40%."
    assert answer.tier == "direct"
    assert dispatcher.seen == ["volume 40"]


async def test_the_socket_is_private_to_this_user(socket_dir):
    server = await serving(Daemon(FakeDispatcher()))
    async with server:
        mode = stat.S_IMODE(os.stat(protocol.socket_path()).st_mode)
    # This process can read files and spend money; nobody else gets to ask it to.
    assert mode & 0o077 == 0


async def test_no_daemon_is_a_clear_error(socket_dir):
    with pytest.raises(client.NoDaemon):
        await client.ask("hello")


async def test_a_stale_socket_file_does_not_block_startup(socket_dir):
    """A daemon killed without cleanup leaves the file behind."""
    stale = protocol.socket_path()
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.touch()
    server = await serving(Daemon(FakeDispatcher()))
    async with server:
        assert (await client.ask("hi")).text == "done"


async def test_a_live_daemon_is_not_displaced(socket_dir):
    """Starting a second daemon must not unlink the first one's socket."""
    server = await serving(Daemon(FakeDispatcher()))
    async with server:
        with pytest.raises(RuntimeError, match="already listening"):
            await _bind(Daemon(FakeDispatcher()))
        assert (await client.ask("still here")).text == "done"


async def test_one_bad_turn_does_not_kill_the_daemon(socket_dir):
    dispatcher = FakeDispatcher(error=RuntimeError("tool exploded"))
    server = await serving(Daemon(dispatcher))
    async with server:
        with pytest.raises(RuntimeError, match="tool exploded"):
            await client.ask("break it")
        # Still serving.
        dispatcher.error = None
        assert (await client.ask("are you there")).text == "done"


async def test_empty_requests_are_rejected_without_reaching_the_dispatcher(socket_dir):
    dispatcher = FakeDispatcher()
    server = await serving(Daemon(dispatcher))
    async with server:
        with pytest.raises(RuntimeError, match="no text"):
            await client.ask("   ")
    assert dispatcher.seen == []


async def test_requests_are_handled_one_at_a_time(socket_dir):
    """Two prompts racing would interleave one machine and one conversation."""
    overlaps = []
    active = 0

    async def slow(text):
        nonlocal active
        active += 1
        overlaps.append(active)
        await asyncio.sleep(0.05)
        active -= 1
        return Reply(text, Tier.DIRECT)

    server = await serving(Daemon(FakeDispatcher(reply=slow)))
    async with server:
        await asyncio.gather(*(client.ask(f"message {i}") for i in range(4)))
    assert max(overlaps) == 1, "requests overlapped"


# --- conversation lifetime ---


async def test_a_long_gap_starts_a_fresh_conversation(socket_dir, monkeypatch):
    jarvis = FakeJarvis()
    daemon = Daemon(FakeDispatcher(), jarvis)
    await daemon.handle_text("first")
    assert jarvis.messages  # the fake's history survived the first turn

    # Pretend half an hour passed since the last message.
    daemon._last_seen -= 10_000
    jarvis.messages = [{"role": "user", "content": "yesterday"}]
    await daemon.handle_text("much later")
    assert jarvis.messages == [], "an old conversation should not colour a new one"


async def test_a_short_gap_keeps_the_conversation(socket_dir):
    jarvis = FakeJarvis()
    daemon = Daemon(FakeDispatcher(), jarvis)
    await daemon.handle_text("first")
    jarvis.messages = [{"role": "user", "content": "recent"}]
    await daemon.handle_text("second")
    assert jarvis.messages, "a follow-up must keep its context"
