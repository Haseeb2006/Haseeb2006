"""The whole free stack, end to end, with nothing mocked but the model weights.

A real MCP server subprocess, a real Unix socket, a real daemon, and a real HTTP
server speaking Ollama's protocol. What this cannot cover is whether a 4B model
makes good decisions — only that every wire between the parts is connected.
"""

from __future__ import annotations

import pytest

from core import client, protocol
from core.daemon import Daemon, _bind
from core.dispatch import Dispatcher
from core.local import LocalModel
from core.machine import Machine
from core.router import Tier
from tests.fake_ollama import FakeOllama, Server


@pytest.fixture
def ollama(monkeypatch):
    state = FakeOllama()
    with Server(state) as server:
        # Only the environment: settings are read when used, so this is all it
        # takes — which is the same reason ~/.jarvis/env works for the daemon.
        monkeypatch.setenv("OLLAMA_HOST", server.host)
        yield state


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "Documents"
    root.mkdir()
    (root / "thesis-draft.pdf").write_text("x")
    monkeypatch.setenv("JARVIS_ALLOWED_ROOTS", str(root))
    monkeypatch.setenv("JARVIS_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("JARVIS_SOCKET", str(tmp_path / "jarvis.sock"))
    monkeypatch.setenv("JARVIS_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    return root


# --- the local tier against a real server ---


async def test_local_model_is_detected(ollama, workspace):
    usable, why = await LocalModel(model="qwen3:4b").status()
    assert usable is True and why == ""


async def test_a_missing_model_is_named(ollama, workspace):
    ollama.models = ["llama3.2:1b"]
    usable, why = await LocalModel(model="qwen3:4b").status()
    assert usable is False
    assert "ollama pull qwen3:4b" in why


async def test_a_general_question_is_answered_locally(ollama, workspace):
    ollama.reply = "Paris is the capital of France."
    async with Machine() as machine:
        dispatcher = Dispatcher(machine, local=LocalModel(), claude=None)
        reply = await dispatcher.handle("what is the capital of France")

    assert reply.tier is Tier.LOCAL
    assert reply.text == "Paris is the capital of France."
    assert ollama.chats, "the local model should have been asked"


async def test_the_local_model_can_refuse_and_escalate(ollama, workspace):
    ollama.reply = "ESCALATE"
    async with Machine() as machine:
        reply = await Dispatcher(machine, local=LocalModel(), claude=None).handle(
            "plan my whole week around my deadlines"
        )
    assert reply.label == "unavailable"  # no Claude configured to escalate to


async def test_a_failing_local_model_does_not_break_the_turn(ollama, workspace):
    ollama.chat_status = 500
    async with Machine() as machine:
        reply = await Dispatcher(machine, local=LocalModel(), claude=None).handle(
            "tell me something"
        )
    assert reply.label == "unavailable"


# --- memory with real embeddings over real HTTP ---


async def test_recall_by_meaning_end_to_end(ollama, workspace):
    from mcp_server import memory_store

    await memory_store.remember("He listens on Apple Music, never Spotify")
    await memory_store.remember("The thesis is due in April")

    # Shares no words with the stored memory: keyword search cannot find this.
    found = await memory_store.recall("what music does he listen to")
    assert found, "semantic recall failed end to end"
    assert "Apple Music" in found[0].text
    assert found[0].matched_by in ("meaning", "both")
    assert ollama.embeds, "embeddings should have gone over HTTP"


async def test_older_ollama_without_the_new_endpoint_still_works(ollama, workspace):
    """Older builds have /api/embeddings and no /api/embed."""
    from mcp_server import memory_store

    ollama.legacy_embeddings = True
    await memory_store.remember("He listens on Apple Music, never Spotify")
    found = await memory_store.recall("what music does he listen to")
    assert found and found[0].matched_by in ("meaning", "both")


async def test_memory_survives_ollama_disappearing(ollama, workspace):
    from mcp_server import memory_store

    await memory_store.remember("The thesis is due in April")
    ollama.embed_status = 503
    # Keyword search carries it: worse, not broken.
    found = await memory_store.recall("thesis")
    assert found and found[0].matched_by == "keyword"


# --- the daemon, over its socket, driving the real MCP server ---


async def test_the_whole_free_path_over_the_socket(ollama, workspace):
    ollama.reply = "ESCALATE"  # force everything through rules, as on a real Mac

    async with Machine() as machine:
        daemon = Daemon(Dispatcher(machine, local=LocalModel(), claude=None))
        server = await _bind(daemon)
        async with server:
            stored = await client.ask("remember that the thesis is due in April")
            assert stored.tier == "direct"
            assert "Remembered" in stored.text

            recalled = await client.ask("what do you remember")
            assert "thesis is due in April" in recalled.text

            found = await client.ask("find thesis")
            assert "thesis-draft.pdf" in found.text
            assert found.tier == "direct"


async def test_memory_is_shared_between_the_socket_and_the_store(ollama, workspace):
    """What is remembered through the daemon is the same store the REPL reads."""
    from mcp_server import memory_store

    async with Machine() as machine:
        server = await _bind(Daemon(Dispatcher(machine, local=None, claude=None)))
        async with server:
            await client.ask("remember that uv beats pip")

    assert any("uv beats pip" in m.text for m in memory_store.recent())


async def test_the_audit_log_records_what_the_daemon_did(ollama, workspace):
    import json

    async with Machine() as machine:
        server = await _bind(Daemon(Dispatcher(machine, local=None, claude=None)))
        async with server:
            await client.ask("find thesis")

    entries = [
        json.loads(line)
        for line in (workspace.parent / "audit.jsonl").read_text().splitlines()
    ]
    assert any(e["tool"] == "search_files" and e["outcome"] == "ok" for e in entries)
