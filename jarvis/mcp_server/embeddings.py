"""Local text embeddings via Ollama.

Optional by design. Without them memory still works on keyword search, so a
missing model degrades recall rather than breaking it.
"""

from __future__ import annotations

import os
from array import array

import httpx2 as httpx

def host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def model() -> str:
    return os.environ.get("JARVIS_EMBED_MODEL", "nomic-embed-text")



def pack(vector: list[float]) -> bytes:
    """Store as normalised float32, so similarity is a plain dot product."""
    magnitude = sum(value * value for value in vector) ** 0.5
    if magnitude == 0:
        return b""
    return array("f", [value / magnitude for value in vector]).tobytes()


def unpack(blob: bytes) -> array:
    vector = array("f")
    vector.frombytes(blob)
    return vector


def similarity(left: array, right: array) -> float:
    """Both sides are already normalised, so the dot product is the cosine."""
    if len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


async def embed(text: str) -> bytes | None:
    """Embed one string, or None if Ollama or the model is unavailable."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{host()}/api/embed", json={"model": model(), "input": text}
            )
            if response.status_code == 404:
                # Older Ollama exposes /api/embeddings with a different shape.
                response = await client.post(
                    f"{host()}/api/embeddings", json={"model": model(), "prompt": text}
                )
                response.raise_for_status()
                return pack(response.json()["embedding"])
            response.raise_for_status()
            return pack(response.json()["embeddings"][0])
    except Exception:
        return None
