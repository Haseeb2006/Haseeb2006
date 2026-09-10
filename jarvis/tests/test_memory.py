"""Memory: storing, finding, and really forgetting."""

from __future__ import annotations

import pytest

from mcp_server import embeddings, memory_store
from mcp_server.tools import memory


@pytest.fixture(autouse=True)
def private_db(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MEMORY_DB", str(tmp_path / "memory.db"))


def no_embeddings(monkeypatch):
    """Ollama absent: memory must still work on keyword search alone."""
    async def none(text):
        return None

    monkeypatch.setattr(embeddings, "embed", none)


def with_embeddings(monkeypatch, vectors):
    """Fake embeddings, so semantic recall can be tested without a model."""
    async def embed(text):
        for needle, vector in vectors.items():
            if needle in text.lower():
                return embeddings.pack(vector)
        return embeddings.pack([0.0, 0.0, 1.0])

    monkeypatch.setattr(embeddings, "embed", embed)


# --- storing ---


async def test_remember_then_recall(monkeypatch):
    no_embeddings(monkeypatch)
    await memory_store.remember("Haseeb uses Apple Music, not Spotify")
    found = await memory_store.recall("Apple Music")
    assert len(found) == 1
    assert "Apple Music" in found[0].text


async def test_saying_it_twice_stores_one_memory(monkeypatch):
    no_embeddings(monkeypatch)
    first = await memory_store.remember("Prefers direct answers")
    second = await memory_store.remember("Prefers direct answers")
    assert second.id == first.id
    assert second.matched_by == "existing"
    assert memory_store.count() == {"fact": 1}


async def test_empty_memories_are_refused(monkeypatch):
    no_embeddings(monkeypatch)
    with pytest.raises(ValueError):
        await memory_store.remember("   ")


# --- finding ---


async def test_keyword_search_works_without_a_model(monkeypatch):
    no_embeddings(monkeypatch)
    await memory_store.remember("The tax return is in Documents/2026")
    found = await memory_store.recall("tax return")
    assert found and found[0].matched_by == "keyword"


async def test_meaning_finds_what_wording_cannot(monkeypatch):
    """"what music do I use" shares no words with "prefers Apple Music"."""
    with_embeddings(monkeypatch, {
        "music": [1.0, 0.0, 0.0],
        "listens": [0.98, 0.2, 0.0],
    })
    await memory_store.remember("He listens on Apple, never on Spotify")
    found = await memory_store.recall("what music app")
    assert found, "semantic recall should have found it"
    assert found[0].matched_by == "meaning"


async def test_found_both_ways_ranks_higher(monkeypatch):
    with_embeddings(monkeypatch, {"budget": [1.0, 0.0, 0.0]})
    await memory_store.remember("The budget spreadsheet lives on the Desktop")
    await memory_store.remember("Something unrelated entirely")
    found = await memory_store.recall("budget")
    assert found[0].matched_by == "both"


async def test_unrelated_memories_are_not_returned(monkeypatch):
    no_embeddings(monkeypatch)
    await memory_store.remember("Haseeb studies B.Tech CSE")
    assert await memory_store.recall("volcano photography") == []


async def test_fts_operators_in_user_text_are_searched_not_parsed(monkeypatch):
    """A memory containing AND / OR / NEAR must not break the query."""
    no_embeddings(monkeypatch)
    await memory_store.remember("Use pytest AND ruff before pushing")
    found = await memory_store.recall("pytest AND ruff")
    assert found, "quoting should have kept this a search, not a syntax error"


async def test_recall_of_nothing_is_empty(monkeypatch):
    no_embeddings(monkeypatch)
    assert await memory_store.recall("") == []


# --- forgetting ---


async def test_forget_really_removes_it(monkeypatch):
    no_embeddings(monkeypatch)
    stored = await memory_store.remember("A thing said in confidence")
    assert memory_store.forget(stored.id).text == "A thing said in confidence"
    # Gone from the table and from the search index, not merely hidden.
    assert await memory_store.recall("confidence") == []
    assert memory_store.count() == {}


async def test_forgetting_something_absent_says_so(monkeypatch):
    no_embeddings(monkeypatch)
    assert memory_store.forget(4242) is None
    with pytest.raises(ValueError, match="no memory with id"):
        await memory.forget(memory_id=4242)


async def test_the_same_text_can_be_stored_again_after_forgetting(monkeypatch):
    no_embeddings(monkeypatch)
    first = await memory_store.remember("Something reversible")
    memory_store.forget(first.id)
    again = await memory_store.remember("Something reversible")
    assert again.matched_by == "new"
    assert (await memory_store.recall("reversible"))


# --- the tool layer ---


async def test_remember_tool_reports_whether_it_was_new(monkeypatch):
    no_embeddings(monkeypatch)
    first = await memory.remember(text="Uses uv, not pip")
    second = await memory.remember(text="Uses uv, not pip")
    assert first["stored"] is True and first["already_known"] is False
    assert second["stored"] is False and second["already_known"] is True


async def test_recall_tool_caps_the_limit(monkeypatch):
    no_embeddings(monkeypatch)
    for index in range(30):
        await memory_store.remember(f"Fact number {index} about testing")
    assert (await memory.recall(query="testing", limit=999))["count"] <= 20


async def test_list_memories_is_newest_first(monkeypatch):
    no_embeddings(monkeypatch)
    await memory_store.remember("First thing")
    await memory_store.remember("Second thing")
    listed = (await memory.list_memories())["memories"]
    assert listed[0]["text"] == "Second thing"


async def test_forget_rejects_a_non_number(monkeypatch):
    no_embeddings(monkeypatch)
    with pytest.raises(ValueError, match="must be a number"):
        await memory.forget(memory_id="the one about music")


# --- the database itself ---


def test_the_database_is_not_world_readable(monkeypatch, tmp_path):
    import os
    import stat

    memory_store.connect().close()
    mode = stat.S_IMODE(os.stat(memory_store.db_path()).st_mode)
    assert mode & 0o077 == 0, "memories are personal; keep them owner-only"
