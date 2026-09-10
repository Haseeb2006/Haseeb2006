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

STEP = 10  # what "louder" and "quieter" mean, in percentage points

STATUS_WORDS = r"battery|charge|status|wifi|wi-?fi|network|disk|storage|space|uptime"

# Each pair is written together so neither direction can be forgotten.
RULES: list[tuple[re.Pattern[str], str]] = [
    # Volume, relative. "up"/"down" need the current level, so they are their own
    # tool rather than a read followed by a write.
    (re.compile(r"(?:turn\s+)?(?:the\s+)?volume\s+up|louder|turn\s+it\s+up", re.I), "louder"),
    (re.compile(r"(?:turn\s+)?(?:the\s+)?volume\s+down|quieter|turn\s+it\s+down", re.I), "quieter"),
    (re.compile(r"un-?mute(?:\s+(?:the\s+)?(?:volume|sound|audio))?", re.I), "unmute"),
    # Playback.
    (re.compile(r"(?:what(?:'|’)?s|what\s+is)?\s*(?:currently\s+)?(?:now\s+)?playing", re.I), "now_playing"),
    (re.compile(r"(?:play|resume)(?:\s+(?:the\s+)?(?:music|song|track))?", re.I), "play"),
    (re.compile(r"(?:pause|stop)(?:\s+(?:the\s+)?(?:music|song|track|playback))?", re.I), "pause"),
    (re.compile(r"(?:next|skip)(?:\s+(?:the\s+)?(?:track|song))?", re.I), "next"),
    (re.compile(r"(?:previous|prev|last|go\s+back)(?:\s+(?:the\s+)?(?:track|song))?", re.I), "previous"),
    # Wi-Fi power. "wifi" alone is a question and matches the status rule above.
    (re.compile(r"(?:turn\s+)?(?:on\s+)?(?:the\s+)?wi-?fi\s+on|turn\s+on\s+(?:the\s+)?wi-?fi|enable\s+wi-?fi", re.I), "wifi_on"),
    (re.compile(r"(?:turn\s+)?(?:the\s+)?wi-?fi\s+off|turn\s+off\s+(?:the\s+)?wi-?fi|disable\s+wi-?fi", re.I), "wifi_off"),
    # Appearance.
    (re.compile(r"(?:turn\s+on\s+)?dark\s*mode(?:\s+on)?|go\s+dark", re.I), "dark_on"),
    (re.compile(r"(?:turn\s+on\s+)?light\s*mode(?:\s+on)?|dark\s*mode\s+off|turn\s+off\s+dark\s*mode", re.I), "dark_off"),
    # Clipboard: reading is safe; writing takes free text and stays with a model.
    (re.compile(r"(?:what(?:'|’)?s|what\s+is)?\s*(?:on|in)?\s*(?:my|the)?\s*clipboard|read\s+(?:the\s+)?clipboard|paste", re.I), "read_clipboard"),
    # One-way by nature: there is no software unlock.
    (re.compile(r"lock(?:\s+(?:the\s+|my\s+)?(?:screen|mac|computer|laptop))?", re.I), "lock_screen"),
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
            return Decision(Tier.DIRECT, "set_mute", {"muted": True}, "mute")

        if tool == "unmute":
            return Decision(Tier.DIRECT, "set_mute", {"muted": False}, "unmute")

        if tool in ("louder", "quieter"):
            step = STEP if tool == "louder" else -STEP
            return Decision(Tier.DIRECT, "change_volume", {"delta": step}, tool)

        if tool in ("play", "pause", "next", "previous"):
            return Decision(Tier.DIRECT, "media_control", {"action": tool}, tool)

        if tool in ("wifi_on", "wifi_off"):
            return Decision(Tier.DIRECT, "set_wifi", {"on": tool == "wifi_on"}, tool)

        if tool in ("dark_on", "dark_off"):
            return Decision(Tier.DIRECT, "set_dark_mode", {"on": tool == "dark_on"}, tool)

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
