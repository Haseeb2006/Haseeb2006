"""A server that speaks Ollama's HTTP API, for tests.

Not a mock of our client — a real HTTP server on a real port, answering with
Ollama's actual response shapes. It exists because model weights cannot be
downloaded in every environment, so this exercises everything except the
weights: the request shapes, the response parsing, the failure paths.

Embeddings are deterministic character-trigram hashes. Crude next to a real
model, but genuinely similar text produces genuinely similar vectors, so
semantic recall is exercised with real arithmetic rather than canned answers.
"""

from __future__ import annotations

import json
import math
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIMENSIONS = 64


def trigram_vector(text: str) -> list[float]:
    """A deterministic embedding: hashed character trigrams, L2-normalised."""
    vector = [0.0] * DIMENSIONS
    cleaned = f"  {text.lower().strip()}  "
    for index in range(len(cleaned) - 2):
        trigram = cleaned[index : index + 3]
        # crc32, not hash(): the builtin is salted per process, so the same
        # text would embed differently in the daemon than in the test.
        vector[zlib.crc32(trigram.encode("utf-8")) % DIMENSIONS] += 1.0
    magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / magnitude for value in vector]


class FakeOllama:
    """Controls what the server does, so a test can steer it."""

    def __init__(self, models=("qwen3:4b", "nomic-embed-text")):
        self.models = list(models)
        self.reply = "A plain answer."
        self.chat_status = 200
        self.embed_status = 200
        self.tags_status = 200
        self.chats: list[dict] = []
        self.embeds: list[str] = []
        self.legacy_embeddings = False  # older Ollama: /api/embeddings only


class _Handler(BaseHTTPRequestHandler):
    state: FakeOllama

    def log_message(self, *args):  # keep test output clean
        pass

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/api/tags":
            if self.state.tags_status != 200:
                return self._send(self.state.tags_status, {"error": "unavailable"})
            return self._send(
                200, {"models": [{"name": name} for name in self.state.models]}
            )
        self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length) or b"{}")

        if self.path == "/api/chat":
            self.state.chats.append(request)
            if self.state.chat_status != 200:
                return self._send(self.state.chat_status, {"error": "model failed"})
            return self._send(
                200,
                {
                    "model": request.get("model"),
                    "message": {"role": "assistant", "content": self.state.reply},
                    "done": True,
                },
            )

        if self.path == "/api/embed":
            if self.state.legacy_embeddings:
                # Older Ollama has no /api/embed at all.
                return self._send(404, {"error": "not found"})
            if self.state.embed_status != 200:
                return self._send(self.state.embed_status, {"error": "no such model"})
            text = request.get("input", "")
            self.state.embeds.append(text)
            return self._send(200, {"embeddings": [trigram_vector(text)]})

        if self.path == "/api/embeddings":
            text = request.get("prompt", "")
            self.state.embeds.append(text)
            return self._send(200, {"embedding": trigram_vector(text)})

        self._send(404, {"error": "not found"})


class Server:
    def __init__(self, state: FakeOllama):
        self.state = state
        handler = type("Handler", (_Handler,), {"state": state})
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def host(self) -> str:
        return f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def __enter__(self) -> "Server":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)
