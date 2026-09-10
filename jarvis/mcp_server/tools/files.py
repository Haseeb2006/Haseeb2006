"""GREEN — find files, confined to the allowlisted roots."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

from .. import config, macos

MAX_RESULTS = 50


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


async def _spotlight(query: str, roots: list[Path], limit: int) -> list[Path]:
    """Ask Spotlight. `mdfind` takes the query as one argv item — never a shell."""
    found: list[Path] = []
    for root in roots:
        result = await macos.run(
            "mdfind", "-onlyin", str(root), "-name", query, timeout=15.0
        )
        if not result.ok:
            continue
        for line in result.stdout.splitlines():
            if line.strip():
                found.append(Path(line.strip()))
            if len(found) >= limit:
                return found
    return found


def _walk(query: str, roots: list[Path], limit: int) -> list[Path]:
    """Fallback when Spotlight is unavailable (or we are not on macOS)."""
    pattern = f"*{query.lower()}*"
    found: list[Path] = []
    for root in roots:
        for path in root.rglob("*"):
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            if fnmatch.fnmatch(path.name.lower(), pattern):
                found.append(path)
                if len(found) >= limit:
                    return found
    return found


async def search_files(query: str, limit: int = 20) -> dict[str, Any]:
    """Search for files by name across the allowlisted directories.

    Uses Spotlight, so it is fast even over large folders. `query` matches against
    the filename, not the contents. Results outside the configured roots are
    discarded even if Spotlight returns them.

    Args:
        query: Text to match in the filename, e.g. "invoice" or "resume.pdf".
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

    if macos.is_macos():
        try:
            candidates = await _spotlight(query, roots, limit * 2)
        except (FileNotFoundError, TimeoutError):
            candidates = _walk(query, roots, limit * 2)
    else:
        candidates = _walk(query, roots, limit * 2)

    # Re-check every hit against the allowlist: Spotlight can follow a symlink out
    # of a root, and the tool's contract is that nothing outside it is ever named.
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
