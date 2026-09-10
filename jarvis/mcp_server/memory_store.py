"""Durable memory: SQLite, with keyword search always and meaning when available.

Two searches, because either alone has a hole. Keyword search cannot connect
"what music do I use" to "prefers Apple Music"; semantic search cannot reliably
find a specific string like "budget.xlsx". Results from both are merged.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import embeddings

FACT = "fact"
CONVERSATION = "conversation"
KINDS = (FACT, CONVERSATION)

# How many embedded rows to score per recall. Similarity is computed in Python,
# so this bounds the work; newest rows are scored first.
MAX_SEMANTIC_SCAN = 2000

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,
    text       TEXT NOT NULL,
    source     TEXT,
    created_at TEXT NOT NULL,
    embedding  BLOB
);
CREATE INDEX IF NOT EXISTS memories_kind ON memories(kind, id DESC);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(text, content='');
"""


def db_path() -> Path:
    return Path(os.environ.get("JARVIS_MEMORY_DB", "~/.jarvis/memory.db")).expanduser()


@dataclass
class Memory:
    id: int
    kind: str
    text: str
    created_at: str
    source: str | None = None
    score: float = 0.0
    matched_by: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "created_at": self.created_at,
            "matched_by": self.matched_by,
        }


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    existed = path.exists()
    connection = sqlite3.connect(path)
    if not existed:
        os.chmod(path, 0o600)  # memories are personal; do not leave them readable
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def _escape_fts(query: str) -> str:
    """Quote each word, so FTS5 operators in user text are searched, not parsed."""
    words = [word.replace('"', "") for word in query.split()]
    return " OR ".join(f'"{word}"' for word in words if word)


async def remember(text: str, *, kind: str = FACT, source: str | None = None) -> Memory:
    text = (text or "").strip()
    if not text:
        raise ValueError("there is nothing to remember")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")

    vector = await embeddings.embed(text)
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with connect() as connection:
        existing = connection.execute(
            "SELECT id, kind, text, created_at, source FROM memories "
            "WHERE kind = ? AND text = ?",
            (kind, text),
        ).fetchone()
        if existing:
            # Saying the same thing twice should not make two memories.
            return Memory(**dict(existing), matched_by="existing")

        cursor = connection.execute(
            "INSERT INTO memories (kind, text, source, created_at, embedding) "
            "VALUES (?, ?, ?, ?, ?)",
            (kind, text, source, created, vector),
        )
        connection.execute(
            "INSERT INTO memories_fts (rowid, text) VALUES (?, ?)",
            (cursor.lastrowid, text),
        )
        return Memory(cursor.lastrowid, kind, text, created, source, matched_by="new")


def _keyword_hits(connection, query: str, limit: int) -> dict[int, Memory]:
    escaped = _escape_fts(query)
    if not escaped:
        return {}
    try:
        rows = connection.execute(
            "SELECT m.id, m.kind, m.text, m.created_at, m.source, "
            "       bm25(memories_fts) AS rank "
            "FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid "
            "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
            (escaped, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    # bm25 is negative and lower is better; map it into a positive-is-better score.
    return {
        row["id"]: Memory(
            row["id"], row["kind"], row["text"], row["created_at"], row["source"],
            score=1.0 / (1.0 + abs(row["rank"])), matched_by="keyword",
        )
        for row in rows
    }


async def _semantic_hits(connection, query: str, limit: int) -> dict[int, Memory]:
    vector = await embeddings.embed(query)
    if not vector:
        return {}
    target = embeddings.unpack(vector)

    rows = connection.execute(
        "SELECT id, kind, text, created_at, source, embedding FROM memories "
        "WHERE embedding IS NOT NULL AND length(embedding) > 0 "
        "ORDER BY id DESC LIMIT ?",
        (MAX_SEMANTIC_SCAN,),
    ).fetchall()

    scored = []
    for row in rows:
        score = embeddings.similarity(target, embeddings.unpack(row["embedding"]))
        if score > 0.35:  # below this, matches are noise rather than recall
            scored.append((score, row))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    return {
        row["id"]: Memory(
            row["id"], row["kind"], row["text"], row["created_at"], row["source"],
            score=score, matched_by="meaning",
        )
        for score, row in scored[:limit]
    }


async def recall(query: str, *, limit: int = 5, kind: str | None = None) -> list[Memory]:
    query = (query or "").strip()
    if not query:
        return []

    with connect() as connection:
        keyword = _keyword_hits(connection, query, limit * 2)
        semantic = await _semantic_hits(connection, query, limit * 2)

    merged: dict[int, Memory] = dict(keyword)
    for identifier, memory in semantic.items():
        if identifier in merged:
            # Found both ways: more trustworthy than either alone.
            merged[identifier].score += memory.score
            merged[identifier].matched_by = "both"
        else:
            merged[identifier] = memory

    found = [m for m in merged.values() if kind is None or m.kind == kind]
    found.sort(key=lambda m: m.score, reverse=True)
    return found[:limit]


def forget(memory_id: int) -> Memory | None:
    """Delete one memory for good. Returns what was deleted, or None."""
    with connect() as connection:
        row = connection.execute(
            "SELECT id, kind, text, created_at, source FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()
        if row is None:
            return None
        connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        # A contentless FTS5 table takes deletions through its command syntax,
        # and needs the original text to unindex the row.
        connection.execute(
            "INSERT INTO memories_fts (memories_fts, rowid, text) "
            "VALUES ('delete', ?, ?)",
            (memory_id, row["text"]),
        )
        return Memory(**dict(row), matched_by="deleted")


def recent(limit: int = 20, kind: str | None = None) -> list[Memory]:
    with connect() as connection:
        if kind:
            rows = connection.execute(
                "SELECT id, kind, text, created_at, source FROM memories "
                "WHERE kind = ? ORDER BY id DESC LIMIT ?", (kind, limit)
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT id, kind, text, created_at, source FROM memories "
                "ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
    return [Memory(**dict(row)) for row in rows]


def count() -> dict[str, int]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT kind, COUNT(*) AS n FROM memories GROUP BY kind"
        ).fetchall()
    return {row["kind"]: row["n"] for row in rows}
