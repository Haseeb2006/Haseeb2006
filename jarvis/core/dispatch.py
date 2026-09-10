"""Routing a message to the cheapest tier that can actually handle it.

    0  a rule and one tool call ....... free, instant
    1  the local model ................ free, ~a second
    2  Claude .......................... paid

Escalation is one-way. A tier that cannot handle a message passes it up; nothing
ever comes back down mid-message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .machine import ToolFailed
from .router import Decision, Tier, match_direct

# If a message is about this Mac, the local model must not attempt it — it has no
# tools and would answer from imagination. Straight to the tier that can act.
MACHINE_WORDS = (
    "file", "folder", "app", "battery", "volume", "wifi", "wi-fi", "network",
    "disk", "storage", "shortcut", "open", "launch", "close", "screen",
    "mute", "download", "desktop", "document", "music", "spotlight", "finder",
    "quit", "whatsapp", "safari", "chrome", "terminal", "running",
    "clipboard", "playing", "track", "song", "play", "pause", "lock",
    "louder", "quieter", "dark mode", "light mode", "brightness",
)


def needs_machine(text: str) -> bool:
    lowered = f" {text.lower()} "
    return any(f" {word}" in lowered for word in MACHINE_WORDS)


@dataclass
class Reply:
    text: str
    tier: Tier
    tool: str | None = None
    # Overrides the tier name shown to the user, for replies that no tier
    # actually produced — saying "local" for a message the local model never
    # saw is a small lie about where the answer came from.
    label: str | None = None


def _summarise(tool: str, arguments: dict[str, Any], result: Any) -> str:
    """Phrase a tool result without a model. Deterministic, so it stays free."""
    if tool == "set_volume":
        return f"Volume set to {result.get('volume_percent')}%."

    if tool == "open_app":
        return f"Opened {result.get('opened', arguments.get('name'))}."

    if tool == "quit_app":
        if result.get("already_closed"):
            return result.get("note", f"{arguments.get('name')} is not running.")
        return f"Closed {result.get('quit')}."

    if tool == "change_volume":
        return f"Volume {result.get('volume_percent')}% (was {result.get('previous_percent')}%)."

    if tool == "set_mute":
        return "Muted." if result.get("muted") else "Unmuted."

    if tool == "set_wifi":
        return f"Wi-Fi {'on' if result.get('wifi_on') else 'off'}."

    if tool == "set_dark_mode":
        return "Dark mode on." if result.get("dark_mode") else "Light mode on."

    if tool == "lock_screen":
        return "Locked."

    if tool == "media_control":
        if not result.get("applied"):
            return result.get("note", "Nothing to control.")
        return {
            "play": "Playing.", "pause": "Paused.",
            "next": "Skipped ahead.", "previous": "Went back.",
            "playpause": "Toggled playback.",
        }.get(result.get("action"), "Done.")

    if tool == "now_playing":
        if not result.get("track"):
            return result.get("note", "Nothing is playing.")
        line = f"{result['track']}"
        if result.get("artist"):
            line += f" — {result['artist']}"
        return line if result.get("playing") else f"{line} (paused)"

    if tool == "read_clipboard":
        if result.get("empty"):
            return "The clipboard is empty."
        text = result.get("text", "")
        preview = text if len(text) <= 400 else text[:400] + f"… ({len(text)} chars)"
        return f"Clipboard:\n{preview}"

    if tool == "system_status":
        parts = []
        battery = result.get("battery") or {}
        if battery:
            parts.append(f"Battery {battery.get('percent')}% ({battery.get('state')})")
        if result.get("volume_percent") is not None:
            parts.append(f"volume {result['volume_percent']}%")
        if result.get("wifi_network"):
            parts.append(f"on {result['wifi_network']}")
        disk = result.get("disk") or {}
        if disk:
            parts.append(f"{disk.get('free_gb')}GB free")
        if result.get("frontmost_app"):
            parts.append(f"{result['frontmost_app']} in front")
        line = ", ".join(parts) or "No readings available."
        notes = result.get("notes") or []
        return line + ("\n" + "\n".join(notes) if notes else "")

    if tool == "search_files":
        found = result.get("results") or []
        if not found:
            return f"Nothing named {arguments.get('query')!r} in the allowed folders."
        listed = "\n".join(f"  {item['path']}" for item in found[:10])
        more = f"\n  … and {len(found) - 10} more" if len(found) > 10 else ""
        return f"{result.get('count')} match(es):\n{listed}{more}"

    if tool == "list_shortcuts":
        names = [s["name"] for s in result.get("shortcuts", [])]
        return "Shortcuts: " + (", ".join(names) if names else "none found.")

    return str(result)


class Dispatcher:
    def __init__(self, machine: Any, local: Any = None, claude: Any = None) -> None:
        self.machine = machine
        self.local = local
        self.claude = claude

    async def _direct(self, decision: Decision) -> Reply | None:
        """Run a tier-0 rule. Returns None if it turned out not to apply."""
        try:
            result = await self.machine.call(decision.tool, decision.arguments)
        except ToolFailed:
            # The rule matched the words but not the world — "open the pod bay
            # doors" is not an app. Fall through and let a model read the
            # sentence properly, rather than reporting a confusing tool error.
            return None
        return Reply(
            _summarise(decision.tool, decision.arguments, result),
            Tier.DIRECT,
            decision.tool,
        )

    async def handle(self, text: str) -> Reply:
        decision = match_direct(text)
        if decision is not None and decision.tool:
            reply = await self._direct(decision)
            if reply is not None:
                return reply

        if self.local is not None and not needs_machine(text):
            answer = await self.local.answer(text)
            if answer is not None:
                return Reply(answer, Tier.LOCAL)

        if self.claude is None:
            return Reply(
                "That one needs Claude, and no API key is set.\n"
                "  export ANTHROPIC_API_KEY=sk-ant-…   (or rephrase as a direct "
                "command like 'volume 40' or 'open Music')",
                Tier.LOCAL,
                label="unavailable",
            )

        return Reply(await self.claude.ask(text), Tier.CLAUDE)
