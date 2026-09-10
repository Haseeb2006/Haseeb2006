"""GREEN — find files, confined to the allowlisted roots."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .. import config, macos

MAX_RESULTS = 50
MAX_SCAN = 20_000  # entries examined per root before a walk gives up


def _describe(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
        size, modified = stat.st_size, stat.st_mtime
    except OSError:
        size, modified = None, None
    return {
        "path": str(path),
        "name": path.name,
        "size_bytes": size,
        "modified_epoch": modified,
    }


async def _spotlight_root(query: str, root: Path, limit: int) -> list[Path]:
    """Ask Spotlight about one root. `mdfind` takes the query as one argv item."""
    result = await macos.run(
        "mdfind", "-onlyin", str(root), "-name", query, timeout=15.0
    )
    if not result.ok:
        return []
    found: list[Path] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            found.append(Path(line))
        if len(found) >= limit:
            break
    return found


def _walk_root(query: str, root: Path, limit: int) -> list[Path]:
    """Walk one root directly. Bounded by MAX_SCAN so a huge tree cannot hang."""
    needle = query.lower()
    found: list[Path] = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root, onerror=None):
        # Prune dot-directories in place so we never descend into .git or .venv.
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in dirnames + filenames:
            scanned += 1
            if scanned > MAX_SCAN:
                return found
            if name.startswith("."):
                continue
            if needle in name.lower():
                found.append(Path(dirpath) / name)
                if len(found) >= limit:
                    return found
    return found


async def _find(query: str, roots: list[Path], limit: int) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        remaining = limit - len(found)
        if remaining <= 0:
            break

        hits: list[Path] = []
        if macos.is_macos():
            try:
                hits = await _spotlight_root(query, root, remaining)
            except (FileNotFoundError, TimeoutError):
                hits = []

        if not hits:
            # An empty Spotlight result is NOT proof the file is absent. Spotlight
            # does not index everything: temp directories, external volumes with
            # indexing off, anything in System Settings > Spotlight > Privacy, and
            # files created seconds ago all come back empty. Walk the root instead
            # of reporting "no such file".
            hits = _walk_root(query, root, remaining)

        found.extend(hits)
    return found


async def search_files(query: str, limit: int = 20) -> dict[str, Any]:
    """Search for files and folders by name across the allowlisted directories.

    Uses Spotlight where it can, and falls back to reading the folder directly
    when Spotlight has no index for it. `query` matches anywhere in the name, not
    in the file's contents.

    Args:
        query: Text to match in the name, e.g. "invoice" or "resume.pdf".
        limit: Maximum results to return (1-50).
    """
    query = query.strip()
    if not query:
        raise ValueError("query must not be empty")
    limit = max(1, min(int(limit), MAX_RESULTS))

    roots = config.allowed_roots()
    if not roots:
        raise ValueError(
            "No allowed roots exist. Set JARVIS_ALLOWED_ROOTS to directories to search."
        )

    # Over-fetch, because the allowlist re-check below discards some candidates.
    candidates = await _find(query, roots, limit * 2)

    # Re-check every hit: Spotlight can follow a symlink out of a root, and the
    # tool's contract is that nothing outside the allowlist is ever named.
    results: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            safe = config.resolve_within_roots(candidate)
        except config.PathNotAllowed:
            continue
        results.append(_describe(safe))
        if len(results) >= limit:
            break

    return {
        "query": query,
        "count": len(results),
        "searched_roots": [str(r) for r in roots],
        "results": results,
    }
