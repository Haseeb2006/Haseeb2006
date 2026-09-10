"""Tier 0: deciding what never needs a model at all.

A rule here fires with no LLM anywhere in the loop, so a false positive is an
action taken for a sentence that meant something else, with nothing to catch it.
Every pattern therefore matches the *whole* message, free-text captures are
capped and screened, and anything at all doubtful falls through to a model.

Being wrong costs more than being unhelpful: not matching sends the message one
tier up, which is merely slower.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class Tier(IntEnum):
    DIRECT = 0   # a rule here, no model
    LOCAL = 1    # the local model
    CLAUDE = 2   # the API


@dataclass(frozen=True)
class Decision:
    tier: Tier
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    why: str = ""


# A captured phrase containing any of these is doing more than naming a thing.
CLAUSE_MARKERS = (" and ", " then ", " but ", " if ", " so ", ",", ";", "?")

# Words that mean the sentence is about something other than launching an app.
NOT_AN_APP = {
    "a", "an", "the", "up", "new", "file", "files", "folder", "window", "tab",
    "door", "doors", "issue", "pr", "account", "session", "project", "one",
    "tabs", "windows", "everything", "all", "this", "that", "it", "my",
}

STATUS_WORDS = r"battery|charge|status|wifi|wi-?fi|network|disk|storage|space|uptime"

RULES: list[tuple[re.Pattern[str], str]] = [
    # Volume. A bare number is unambiguous; the range is checked by the tool.
    (re.compile(r"(?:set\s+)?volume\s*(?:to\s*)?(?P<level>\d{1,3})\s*%?", re.I), "set_volume"),
    (re.compile(r"mute(?:\s+(?:the\s+)?(?:volume|sound|audio))?", re.I), "mute"),
    # Machine state. All of these are one read.
    (re.compile(
        rf"(?:what(?:'|’)?s|what\s+is|how(?:'|’)?s|hows|how|check|show(?:\s+me)?)?\s*"
        rf"(?:my|the|system)?\s*(?:much\s+)?(?:free\s+)?(?:{STATUS_WORDS})"
        rf"(?:\s+(?:level|space|left|status|percent|percentage))?",
        re.I), "system_status"),
    # Shortcuts: listing them is read-only. Running one is RED and never lands here.
    (re.compile(r"(?:list|show)?\s*(?:my|the)?\s*shortcuts", re.I), "list_shortcuts"),
    # Free-text captures, screened below.
    (re.compile(r"(?:open|launch|start|fire\s+up)\s+(?:the\s+|my\s+)?(?P<name>.+)", re.I), "open_app"),
    (re.compile(r"(?:close|quit|exit)\s+(?:the\s+|my\s+)?(?P<name>.+)", re.I), "quit_app"),
    (re.compile(r"(?:find|search\s+for|locate|look\s+for)\s+(?:my\s+|the\s+|a\s+)?(?P<query>.+)", re.I), "search_files"),
]


def _clean(text: str) -> str:
    """Collapse whitespace and drop trailing punctuation, keeping the case."""
    return re.sub(r"\s+", " ", text).strip().rstrip("?!.")


def _phrase_is_a_plain_name(phrase: str, *, max_words: int = 4) -> bool:
    """Whether a captured phrase just names a thing, rather than asking something."""
    if not phrase or len(phrase) > 60:
        return False
    padded = f" {phrase.lower()} "
    if any(marker in padded for marker in CLAUSE_MARKERS):
        return False
    words = phrase.split()
    if len(words) > max_words:
        return False
    return not all(word.lower() in NOT_AN_APP for word in words)


def match_direct(text: str) -> Decision | None:
    """A tool call for `text`, or None to send it up a tier."""
    cleaned = _clean(text)
    if not cleaned:
        return None

    for pattern, tool in RULES:
        found = pattern.fullmatch(cleaned)
        if not found:
            continue
        groups = found.groupdict()

        if tool == "set_volume":
            level = int(groups["level"])
            if not 0 <= level <= 100:
                return None  # let a model explain the range
            return Decision(Tier.DIRECT, "set_volume", {"level": level}, "volume")

        if tool == "mute":
            return Decision(Tier.DIRECT, "set_volume", {"level": 0}, "mute")

        if tool == "open_app":
            name = groups["name"].strip()
            if not _phrase_is_a_plain_name(name):
                return None
            return Decision(Tier.DIRECT, "open_app", {"name": name}, "open app")

        if tool == "quit_app":
            name = groups["name"].strip()
            if not _phrase_is_a_plain_name(name):
                return None
            return Decision(Tier.DIRECT, "quit_app", {"name": name}, "quit app")

        if tool == "search_files":
            query = groups["query"].strip()
            if not _phrase_is_a_plain_name(query, max_words=5):
                return None
            return Decision(Tier.DIRECT, "search_files", {"query": query}, "file search")

        return Decision(Tier.DIRECT, tool, {}, tool)

    return None
