"""Exercise every tool on this Mac and report what actually works.

    uv run python selftest.py                 # safe checks only
    uv run python selftest.py --disruptive    # also plays/pauses, toggles Wi-Fi

Safe by default: read-only tools run freely, and reversible ones are restored to
the state they were in. Anything that would interrupt you — playback, Wi-Fi
power, opening or quitting apps, locking the screen — needs --disruptive.
`run_shortcut` is never exercised; it is RED and could send a message.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from core.machine import Machine, ToolFailed

GREEN, RED, DIM, YELLOW, OFF = "\033[32m", "\033[31m", "\033[2m", "\033[33m", "\033[0m"

results: list[tuple[str, str, str]] = []


def record(name: str, state: str, detail: str = "") -> None:
    mark = {"ok": f"{GREEN}  ok  {OFF}", "FAIL": f"{RED} FAIL {OFF}",
            "skip": f"{DIM} skip {OFF}"}[state]
    print(f"[{mark}] {name:16} {detail}")
    results.append((name, state, detail))


async def check(machine: Machine, name: str, arguments: dict, describe=None) -> dict | None:
    try:
        result = await machine.call(name, arguments)
    except ToolFailed as exc:
        record(name, "FAIL", str(exc).replace("\n", " ")[:150])
        return None
    except Exception as exc:  # noqa: BLE001
        record(name, "FAIL", f"{type(exc).__name__}: {exc}"[:150])
        return None
    record(name, "ok", describe(result) if describe else "")
    return result


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disruptive", action="store_true",
                        help="also test playback, Wi-Fi power, and app launching")
    args = parser.parse_args()

    print("jarvis selftest\n")
    if sys.platform != "darwin":
        print(f"{YELLOW}Not macOS — every tool here will report that.{OFF}\n")

    async with Machine() as machine:
        print(f"{DIM}{len(machine.tool_names)} tools{OFF}\n")

        # --- read-only ---
        status = await check(
            machine, "system_status", {},
            lambda r: f"battery {(r.get('battery') or {}).get('percent')}%, "
                      f"volume {r.get('volume_percent')}%, "
                      f"muted={r.get('muted')}, dark={r.get('dark_mode')}",
        )
        for note in (status or {}).get("notes", []):
            print(f"{DIM}         note: {note.splitlines()[0]}{OFF}")

        await check(machine, "search_files", {"query": "a", "limit": 3},
                    lambda r: f"{r.get('count')} result(s)")
        await check(machine, "list_shortcuts", {},
                    lambda r: f"{r.get('count')} shortcut(s)")
        await check(machine, "now_playing", {},
                    lambda r: r.get("track") or r.get("note", ""))
        clip = await check(machine, "read_clipboard", {},
                           lambda r: "empty" if r.get("empty") else f"{r.get('length')} chars")

        # --- reversible, restored afterwards ---
        volume = (status or {}).get("volume_percent")
        if volume is None:
            record("change_volume", "skip", "could not read the current volume")
        else:
            changed = await check(machine, "change_volume", {"delta": -5},
                                  lambda r: f"{r.get('previous_percent')}% -> {r.get('volume_percent')}%")
            if changed:
                await machine.call("set_volume", {"level": volume})
                record("set_volume", "ok", f"restored to {volume}%")

        was_muted = (status or {}).get("muted")
        if was_muted is None:
            record("set_mute", "skip", "could not read the mute state")
        else:
            if await check(machine, "set_mute", {"muted": not was_muted},
                           lambda r: f"muted={r.get('muted')}"):
                await machine.call("set_mute", {"muted": was_muted})
                print(f"{DIM}         restored muted={was_muted}{OFF}")

        was_dark = (status or {}).get("dark_mode")
        if was_dark is None:
            record("set_dark_mode", "skip",
                   "could not read appearance (needs Automation permission)")
        else:
            if await check(machine, "set_dark_mode", {"on": not was_dark},
                           lambda r: f"dark={r.get('dark_mode')}"):
                await machine.call("set_dark_mode", {"on": was_dark})
                print(f"{DIM}         restored dark={was_dark}{OFF}")

        if clip is None:
            record("write_clipboard", "skip", "could not read the clipboard first")
        else:
            marker = "jarvis selftest — your clipboard is restored below"
            if await check(machine, "write_clipboard", {"text": marker},
                           lambda r: f"wrote {r.get('length')} chars"):
                # Put back exactly what was there, including nothing at all.
                await machine.call("write_clipboard", {"text": clip.get("text", "")})
                print(f"{DIM}         restored your clipboard{OFF}")

        # --- disruptive ---
        if not args.disruptive:
            for name in ("media_control", "set_wifi", "open_app", "quit_app",
                         "lock_screen"):
                record(name, "skip", "needs --disruptive")
        else:
            await check(machine, "media_control", {"action": "playpause"},
                        lambda r: r.get("note") or "toggled")
            await check(machine, "media_control", {"action": "playpause"},
                        lambda r: r.get("note") or "toggled back")
            await check(machine, "open_app", {"name": "TextEdit"},
                        lambda r: f"opened {r.get('opened')}")
            await asyncio.sleep(2)
            await check(machine, "quit_app", {"name": "TextEdit"},
                        lambda r: r.get("note") or f"quit {r.get('quit')}")
            wifi = (status or {}).get("wifi_network")
            record("set_wifi", "skip",
                   "not toggled — it would drop your connection"
                   if wifi else "not toggled")
            record("lock_screen", "skip", "would lock you out mid-test")

        record("run_shortcut", "skip", "RED — never exercised automatically")

    failed = [name for name, state, _ in results if state == "FAIL"]
    print()
    if failed:
        print(f"{RED}{len(failed)} failed:{OFF} {', '.join(failed)}")
        print("Paste the FAIL lines and I'll fix them.")
        return 1
    print(f"{GREEN}Everything that ran, worked.{OFF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
