"""Model and runtime settings for the agent loop."""

from __future__ import annotations

import os
from pathlib import Path

# Opus 5 takes adaptive thinking; `budget_tokens` is rejected with a 400 on this
# family, and effort is the dial that replaces it.
MODEL = os.environ.get("JARVIS_MODEL", "claude-opus-5")

# Effort is the main cost lever: "low" is right for routine chat and single tool
# calls, "high" for planning and multi-step work. M2's router will choose this
# per turn; until then it is one setting for the session.
EFFORT = os.environ.get("JARVIS_EFFORT", "low")

# Non-streaming requests: 16k keeps responses inside the SDK's HTTP timeout.
MAX_TOKENS = int(os.environ.get("JARVIS_MAX_TOKENS", "16000"))

# Stop a runaway loop rather than letting it spend all night on tool calls.
MAX_ITERATIONS = int(os.environ.get("JARVIS_MAX_ITERATIONS", "12"))

# Opus 5 can decline a request outright (stop_reason "refusal"). Server-side
# fallback re-routes those instead of handing the user a dead end.
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
