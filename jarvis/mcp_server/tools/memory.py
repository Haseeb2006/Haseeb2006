"""Memory tools: remember, recall, and forget.

`forget` really deletes. A memory the user asked you to drop, that turns out to
still be there, is worse than one that was never stored — so there is no quiet
soft-delete pretending otherwise, and the deletion is RED.
"""

from __future__ import annotations

from typing import Any

from .. import memory_store


async def remember(text: str, kind: str = "fact") -> dict[str, Any]:
    """Store something worth keeping across conversations.

    Use this for durable facts about the user, their preferences, their setup and
    their projects — not for passing details of the current conversation.

    Args:
        text: The thing to remember, written as a standalone sentence.
        kind: "fact" for something durable, "conversation" for an exchange.
    """
    memory = await memory_store.remember(text, kind=kind)
    return {
        "id": memory.id,
        "stored": memory.matched_by == "new",
        "already_known": memory.matched_by == "existing",
        "text": memory.text,
    }


async def recall(query: str, limit: int = 5) -> dict[str, Any]:
    """Search everything remembered about the user.

    Matches on meaning as well as wording, so "what music does he use" can find
    "prefers Apple Music". Call it before answering anything personal.

    Args:
        query: What you are trying to remember.
        limit: How many memories to return (1-20).
    """
    limit = max(1, min(int(limit), 20))
    found = await memory_store.recall(query, limit=limit)
    return {
        "query": query,
        "count": len(found),
        "memories": [memory.as_dict() for memory in found],
    }


async def list_memories(limit: int = 20) -> dict[str, Any]:
    """List the most recently stored memories.

    Args:
        limit: How many to list (1-100).
    """
    limit = max(1, min(int(limit), 100))
    found = memory_store.recent(limit=limit)
    return {
        "counts": memory_store.count(),
        "memories": [memory.as_dict() for memory in found],
    }


async def forget(memory_id: int) -> dict[str, Any]:
    """Permanently delete one memory. Get its id from `recall` or `list_memories`.

    Args:
        memory_id: The id of the memory to delete.
    """
    try:
        memory_id = int(memory_id)
    except (TypeError, ValueError):
        raise ValueError(f"memory_id must be a number, got {memory_id!r}") from None

    deleted = memory_store.forget(memory_id)
    if deleted is None:
        raise ValueError(f"There is no memory with id {memory_id}.")
    return {"forgotten": deleted.text, "id": memory_id}
