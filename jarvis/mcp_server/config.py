"""Configuration and the filesystem allowlist.

Everything the server is allowed to touch is decided here. Tools never resolve a
user-supplied path themselves — they go through `resolve_within_roots`.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_ROOTS = ("~/Documents", "~/Desktop", "~/Downloads", "~/Projects")


def _split_env(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def allowed_roots() -> list[Path]:
    """Directories the filesystem tools may read from.

    Read from `JARVIS_ALLOWED_ROOTS` (comma-separated) or a conservative default.
    Roots that do not exist are dropped rather than raising — a missing ~/Projects
    should not take the server down.
    """
    configured = _split_env("JARVIS_ALLOWED_ROOTS") or list(_DEFAULT_ROOTS)
    roots: list[Path] = []
    for entry in configured:
        try:
            root = Path(entry).expanduser().resolve()
        except OSError:
            continue
        if root.is_dir():
            roots.append(root)
    return roots


def allowed_shortcuts() -> set[str]:
    """Shortcut names that may run without a confirmation prompt.

    Empty by default: every RED action has to be confirmed or allowlisted.
    """
    return {name.casefold() for name in _split_env("JARVIS_ALLOWED_SHORTCUTS")}


def audit_log_path() -> Path:
    return Path(
        os.environ.get("JARVIS_AUDIT_LOG", "~/.jarvis/audit.jsonl")
    ).expanduser()


class PathNotAllowed(Exception):
    """A path resolved to somewhere outside every allowed root."""


def resolve_within_roots(candidate: str | Path) -> Path:
    """Resolve `candidate` and confirm it sits inside an allowed root.

    Resolution happens *before* the check, so symlinks, `..`, and `~` cannot be
    used to step outside the allowlist. A symlink inside ~/Documents pointing at
    /etc/passwd resolves to /etc/passwd and is rejected.
    """
    roots = allowed_roots()
    if not roots:
        raise PathNotAllowed(
            "No allowed roots are configured or none exist. "
            "Set JARVIS_ALLOWED_ROOTS to a comma-separated list of directories."
        )

    path = Path(candidate).expanduser()
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise PathNotAllowed(f"Could not resolve {candidate!r}: {exc}") from exc

    for root in roots:
        if resolved == root or root in resolved.parents:
            return resolved

    listed = ", ".join(str(r) for r in roots)
    raise PathNotAllowed(
        f"{resolved} is outside the allowed roots ({listed})."
    )
