"""Tier 1: the local model, via Ollama.

Free and offline. A small model is confident and wrong more often than a large
one, so its job is deliberately narrow: answer general questions, and hand
anything about *this machine* upward rather than guessing at it.
"""

from __future__ import annotations

import os

import httpx2 as httpx

def default_host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def default_model() -> str:
    return os.environ.get("JARVIS_LOCAL_MODEL", "qwen3:4b")

ESCALATE = "ESCALATE"

SYSTEM = f"""You are the local half of an assistant running on a Mac.

Answer only what you are certain of from general knowledge, or ordinary small talk.

Reply with exactly {ESCALATE} and nothing else when the message:
- concerns this Mac — its files, apps, battery, volume, network, shortcuts, settings
- asks you to do something rather than answer something
- needs several steps, or current information, or anything you are unsure about

Never guess about the user's machine. Answer in one or two sentences."""


class LocalModel:
    def __init__(self, model: str | None = None, host: str | None = None) -> None:
        # Resolved now rather than at import, so ~/.jarvis/env is honoured.
        self.model = model or default_model()
        self.host = host or default_host()

    async def installed_models(self) -> list[str]:
        """Model names Ollama has pulled, or [] if Ollama is not reachable."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{self.host}/api/tags")
                response.raise_for_status()
                return [m["name"] for m in response.json().get("models", [])]
        except Exception:
            return []

    async def status(self) -> tuple[bool, str]:
        """(usable, why not). Told plainly, because the fix differs each way."""
        models = await self.installed_models()
        if not models:
            return False, (
                f"Ollama is not running at {self.host}. "
                "Install it (brew install ollama) and run `ollama serve`."
            )
        # Ollama reports "qwen3:4b"; accept a bare "qwen3" as naming the same family.
        if not any(m == self.model or m.startswith(f"{self.model}:") for m in models):
            return False, f"Model {self.model!r} is not pulled. Run: ollama pull {self.model}"
        return True, ""

    async def answer(self, text: str) -> str | None:
        """The local model's reply, or None meaning "send this up a tier"."""
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.host}/api/chat",
                    json={
                        "model": self.model,
                        "stream": False,
                        "think": False,
                        "messages": [
                            {"role": "system", "content": SYSTEM},
                            {"role": "user", "content": text},
                        ],
                    },
                )
                response.raise_for_status()
                reply = response.json().get("message", {}).get("content", "")
        except Exception:
            # Unreachable, timed out, or answered with something unexpected. The
            # tier above can still handle it; a local failure is never terminal.
            return None

        reply = (reply or "").strip()
        if not reply or ESCALATE in reply.upper():
            return None
        return reply
