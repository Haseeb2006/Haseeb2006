"""Model and runtime settings for the agent loop."""

from __future__ import annotations

import os
from pathlib import Path

# Every setting is read when it is used, not when this module is imported.
# The daemon loads ~/.jarvis/env at startup, which is necessarily after its
# imports — constants captured at import time would ignore that file entirely,
# and launchd gives a daemon no other way to be configured.


def model() -> str:
    """Opus 5 takes adaptive thinking; budget_tokens is rejected on this family."""
    return os.environ.get("JARVIS_MODEL", "claude-opus-5")


def effort() -> str:
    """The main cost dial: low for routine chat, high for planning."""
    return os.environ.get("JARVIS_EFFORT", "low")


def max_tokens() -> int:
    """16k keeps a non-streaming response inside the SDK's HTTP timeout."""
    return int(os.environ.get("JARVIS_MAX_TOKENS", "16000"))


def max_iterations() -> int:
    """Stop a runaway loop rather than letting it spend all night on tool calls."""
    return int(os.environ.get("JARVIS_MAX_ITERATIONS", "12"))


# Opus 5 can decline a request outright; server-side fallback re-routes those.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def load_env_file() -> list[str]:
    """Read ~/.jarvis/env into the environment, for processes launchd starts.

    launchd gives a daemon none of your shell environment, so anything exported
    in .zshrc is invisible to it. Existing variables win, so a value set in the
    shell still overrides the file when run by hand.
    """
    path = Path(os.environ.get("JARVIS_ENV_FILE", "~/.jarvis/env")).expanduser()
    if not path.exists():
        return []

    loaded = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
