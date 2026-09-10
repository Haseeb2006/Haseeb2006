"""Tier 0 patterns. No model sees these, so a false positive is an unchecked action."""

from __future__ import annotations

import pytest

from core.router import Tier, match_direct


def route(text):
    decision = match_direct(text)
    return (decision.tool, decision.arguments) if decision else None


# --- things that must match ---


@pytest.mark.parametrize(
    "said,level",
    [
        ("volume 40", 40), ("volume 0", 0), ("volume 100", 100),
        ("set volume to 65", 65), ("Volume 30%", 30), ("volume to 55", 55),
        ("  volume   25  ", 25),
    ],
)
def test_volume(said, level):
    assert route(said) == ("set_volume", {"level": level})


@pytest.mark.parametrize("said", ["mute", "Mute", "mute the sound", "mute audio"])
def test_mute(said):
    assert route(said) == ("set_mute", {"muted": True})


@pytest.mark.parametrize("said", ["unmute", "Unmute", "un-mute", "unmute the sound"])
def test_unmute_is_its_own_command(said):
    """Unmuting restores the previous level; volume 0 would not."""
    assert route(said) == ("set_mute", {"muted": False})


@pytest.mark.parametrize(
    "said",
    [
        "battery", "battery?", "Battery!", "what's my battery",
        "what is my battery level", "how's my battery", "check battery",
        "status", "system status", "wifi", "wi-fi", "what's my network",
        "disk space", "how much free space", "storage", "uptime",
        "show me the battery percentage",
    ],
)
def test_status_questions(said):
    assert route(said) == ("system_status", {})


@pytest.mark.parametrize(
    "said,app",
    [
        ("open Music", "Music"), ("Open Safari", "Safari"),
        ("launch Visual Studio Code", "Visual Studio Code"),
        ("start Terminal", "Terminal"), ("open the App Store", "App Store"),
        ("fire up Notes", "Notes"),
    ],
)
def test_open_app(said, app):
    assert route(said) == ("open_app", {"name": app})


@pytest.mark.parametrize(
    "said,query",
    [
        ("find my resume", "resume"), ("search for invoice", "invoice"),
        ("locate budget.xlsx", "budget.xlsx"), ("find the tax pdf", "tax pdf"),
    ],
)
def test_search(said, query):
    assert route(said) == ("search_files", {"query": query})


@pytest.mark.parametrize("said", ["shortcuts", "list shortcuts", "show my shortcuts"])
def test_list_shortcuts(said):
    assert route(said) == ("list_shortcuts", {})


# --- things that must NOT match: the expensive mistakes ---


@pytest.mark.parametrize(
    "said",
    [
        "open Music and tell me the weather",   # more than one instruction
        "find my resume, then email it",
        "should I open Music?",
        "open a new file",                      # not naming an app
        "open the",
        "what should I name my startup",
        "why is my battery draining so fast",   # wants reasoning, not a reading
        "how do I check the battery on a Mac",
        "write me a script that sets the volume",
        "volume 400",                           # out of range: let a model say so
        "turn the volume down a bit",           # "a bit" is not a step we define
        "find the file I was working on yesterday afternoon",
        "",
        "   ",
    ],
)
def test_falls_through_to_a_model(said):
    assert route(said) is None


def test_red_tools_are_never_reachable_from_tier_zero():
    """run_shortcut can send messages. It must always pass through a model."""
    for said in ("run Send Text", "run the Send Text shortcut", "send text",
                 "run shortcut Morning Briefing", "execute Send Text"):
        decision = match_direct(said)
        assert decision is None or decision.tool != "run_shortcut"


def test_a_match_is_always_tier_zero():
    assert match_direct("volume 40").tier is Tier.DIRECT


# --- closing apps ---


@pytest.mark.parametrize(
    "said,app",
    [
        ("close whatsapp", "whatsapp"), ("Close WhatsApp", "WhatsApp"),
        ("quit Safari", "Safari"), ("close Visual Studio Code", "Visual Studio Code"),
        ("exit Music", "Music"), ("close the Finder", "Finder"),
    ],
)
def test_close_app(said, app):
    assert route(said) == ("quit_app", {"name": app})


@pytest.mark.parametrize(
    "said",
    [
        "close all my tabs",       # not an app
        "close the window",
        "close everything",
        "quit",                    # this leaves the CLI; never a tool call
        "exit",
        "close whatsapp and open Music",
        "should I close whatsapp",
        "how do I quit an app on a Mac",
    ],
)
def test_close_falls_through(said):
    assert route(said) is None


# --- every pair, both ways ---

PAIRED = [
    ("volume up",        ("change_volume", {"delta": 10})),
    ("volume down",      ("change_volume", {"delta": -10})),
    ("louder",           ("change_volume", {"delta": 10})),
    ("quieter",          ("change_volume", {"delta": -10})),
    ("mute",             ("set_mute", {"muted": True})),
    ("unmute",           ("set_mute", {"muted": False})),
    ("play",             ("media_control", {"action": "play"})),
    ("pause",            ("media_control", {"action": "pause"})),
    ("next track",       ("media_control", {"action": "next"})),
    ("previous track",   ("media_control", {"action": "previous"})),
    ("skip",             ("media_control", {"action": "next"})),
    ("turn on wifi",     ("set_wifi", {"on": True})),
    ("turn off wifi",    ("set_wifi", {"on": False})),
    ("wifi off",         ("set_wifi", {"on": False})),
    ("dark mode",        ("set_dark_mode", {"on": True})),
    ("light mode",       ("set_dark_mode", {"on": False})),
    ("dark mode off",    ("set_dark_mode", {"on": False})),
    ("open Music",       ("open_app", {"name": "Music"})),
    ("close Music",      ("quit_app", {"name": "Music"})),
    ("lock screen",      ("lock_screen", {})),
    ("what's playing",   ("now_playing", {})),
    ("clipboard",        ("read_clipboard", {})),
]


@pytest.mark.parametrize("said,expected", PAIRED, ids=[p[0] for p in PAIRED])
def test_every_basic_and_its_opposite(said, expected):
    assert route(said) == expected


def test_no_direction_is_missing_its_opposite():
    """If a rule can turn something on, a rule must be able to turn it off."""
    both_ways = {"change_volume", "set_mute", "set_wifi", "set_dark_mode"}
    seen: dict[str, set] = {tool: set() for tool in both_ways}
    for said, (tool, args) in PAIRED:
        if tool in both_ways:
            seen[tool].add(tuple(sorted((k, v) for k, v in args.items())))
    for tool, variants in seen.items():
        assert len(variants) >= 2, f"{tool} only has one direction routed"


@pytest.mark.parametrize(
    "said",
    [
        "play something by Kendrick",   # picking a track needs a model
        "pause for a second",
        "skip to the good part",
        "lock in",
        "turn the wifi off after 10pm",
        "should I use dark mode",
        "copy this to my clipboard",    # writing takes free text
    ],
)
def test_fancier_phrasings_still_escalate(said):
    assert route(said) is None


# --- memory ---


@pytest.mark.parametrize(
    "said,expected",
    [
        ("remember that I use Apple Music", ("remember", {"text": "I use Apple Music"})),
        ("remember I hate hedging", ("remember", {"text": "I hate hedging"})),
        ("what do you remember", ("list_memories", {})),
        ("what do you know about me", ("list_memories", {})),
        ("recall my music setup", ("recall", {"query": "my music setup"})),
        ("what do you know about my thesis", ("recall", {"query": "my thesis"})),
    ],
)
def test_memory_commands(said, expected):
    assert route(said) == expected


@pytest.mark.parametrize(
    "said",
    ["forget that", "forget memory 3", "forget what I said about Ali", "forget it"],
)
def test_forgetting_never_happens_without_a_model(said):
    """Deletion is permanent, and which memory is meant needs judgement."""
    decision = match_direct(said)
    assert decision is None or decision.tool != "forget"
