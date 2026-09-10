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
def test_mute_is_volume_zero(said):
    assert route(said) == ("set_volume", {"level": 0})


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
        "volume up",                            # relative, needs the current value
        "turn the volume down a bit",
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
