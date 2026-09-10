# JARVIS + MCP — Build Plan

**Target:** macOS · hybrid brain (local model + Claude API) · text first, voice later
**Language:** Python 3.12 (`uv`)

---

## 0. The core idea

Don't build an assistant and *also* build an MCP server. Build the **MCP server as the
assistant's hands**, and make the assistant an **MCP client**.

```
┌─────────────────┐        ┌──────────────────┐
│ Claude Desktop  │───┐    │                  │
│ Claude Code     │   ├───▶│  jarvis-mcp      │──▶ macOS
│ YOUR jarvis app │───┘    │  (the hands)     │    (apps, files, calendar…)
└─────────────────┘  MCP   └──────────────────┘
```

Why this ordering wins:

1. **You get a working Jarvis in a weekend.** Point Claude Desktop at the MCP server and
   you can already say "what's my battery, open Spotify, find that PDF" — before you've
   written a single line of agent code.
2. **Zero duplication.** Tools are written once. Your own agent consumes them through the
   same protocol (`anthropic[mcp]` ships `async_mcp_tool`, which converts MCP tools into
   tool-runner tools directly).
3. **Crash isolation.** A bad AppleScript kills the tool process, not the assistant.
4. **It's a shippable project on its own** — `jarvis-mcp` is a portfolio repo anyone with
   a Mac can `pip install`.

---

## 1. Repo layout

```
jarvis/
├─ mcp_server/                # THE HANDS — standalone MCP server
│  ├─ server.py               # FastMCP entrypoint (stdio transport)
│  ├─ tools/
│  │   ├─ system.py           # battery, wifi, volume, brightness, running apps
│  │   ├─ files.py            # search / read / move / open — allowlisted dirs only
│  │   ├─ apps.py             # AppleScript + JXA bridge
│  │   ├─ shortcuts.py        # `shortcuts run <name>` — the entitlement cheat code
│  │   ├─ calendar.py         # EventKit via pyobjc
│  │   └─ memory.py           # remember / recall
│  ├─ policy.py               # GREEN / AMBER / RED permission tiers
│  └─ audit.py                # append-only JSONL of every call
├─ core/                      # THE BRAIN — your assistant
│  ├─ agent.py                # Claude loop, MCP client
│  ├─ router.py               # local-model triage (the "hybrid" part)
│  ├─ memory.py               # sqlite + sqlite-vec
│  └─ prompts/profile.md      # durable facts about you
├─ ui/
│  ├─ cli.py                  # v1
│  └─ voice.py                # M6
└─ daemon/com.haseeb.jarvis.plist
```

---

## 2. The hybrid brain — three tiers, escalating

| Tier | Handler | Handles | Cost |
|---|---|---|---|
| **0** | Pure Python, regex/keyword | `volume 40`, `lock screen`, `open safari` | free, ~0ms |
| **1** | Local model via Ollama (`qwen3:4b`) | chit-chat, "which tool?", simple Q&A, intent classification | free, ~200ms |
| **2** | Claude Opus 5 (`claude-opus-5`) | multi-step reasoning, anything that chains tools, anything ambiguous | paid |

Router logic: does it need >1 tool, or reasoning, or state mutation? → Tier 2. Otherwise
try Tier 0, then Tier 1, and escalate on low confidence. Escalation must be one-way and
cheap — never round-trip back down mid-task.

**API settings for Tier 2:**
- Model `claude-opus-5`, `thinking: {"type": "adaptive"}` (do NOT use `budget_tokens` —
  it's rejected with a 400 on Opus 5).
- `output_config: {"effort": "low"}` for routine turns, `"high"` for planning/multi-step.
  This is your main cost dial.
- **Prompt caching is the difference between affordable and not.** Order is
  `tools → system → messages`. Freeze the tool definitions and system prompt, put a
  `cache_control` breakpoint after them, and put volatile context (current time, active
  app, battery) *after* the breakpoint. Verify with `usage.cache_read_input_tokens` — if
  it's 0 across turns, something in your prefix is changing every request.
- Use `client.beta.messages.tool_runner()` rather than hand-writing the loop.

---

## 3. Safety model — non-negotiable

This thing runs on your actual machine. Every tool declares a tier:

- **GREEN** (read-only): auto-run. System state, file search, calendar read.
- **AMBER** (reversible write): run, log, show what happened. Create note, add event,
  move file into a staging dir.
- **RED** (destructive or outbound): explicit confirmation with the exact command
  printed. Delete, send message/email, anything outside the allowlist, shell.

Rules:
1. **No raw `bash` tool in v1.** It collapses your whole permission model into one hole.
   Add it in M4 behind RED with the literal command shown for y/n.
2. Filesystem tools take an **allowlist** of roots (`~/Documents`, `~/Desktop`,
   `~/Projects`). Resolve symlinks and reject anything that escapes after resolution.
3. **Audit log from day one** — append-only JSONL: timestamp, tool, args, tier, result,
   who approved. You will not remember what it did at 2am.

---

## 4. macOS specifics

- `osascript -e '...'` and `osascript -l JavaScript` cover most app automation.
- **`shortcuts run "Name"` is the cheat code.** Anything needing entitlements —
  Messages, Reminders, HomeKit, Focus modes — build as a Shortcut in the Shortcuts app,
  then call it by name from Python. No entitlement work, no code signing.
- `pyobjc-framework-EventKit` for calendar/reminders, `CoreWLAN` for wifi, `IOKit` for
  battery.
- **TCC gotcha:** Automation / Accessibility / Full Disk Access attach to the *parent
  binary*. Grants you give iTerm do not carry to a launchd-loaded daemon — you re-approve
  everything once when you move to M5. Budget an afternoon for it, don't be surprised.
- Daemon: `~/Library/LaunchAgents/com.haseeb.jarvis.plist`, `RunAtLoad` + `KeepAlive`.

---

## 5. Memory

- `profile.md` — hand-written facts about you, always in the cached system prompt.
- **Episodic:** SQLite table `(ts, user_msg, assistant_msg, tools_used)`, embedded locally
  with Ollama `nomic-embed-text`, searched via `sqlite-vec`. No cloud, no vector DB service.
- Expose `remember(fact)` / `recall(query)` as MCP tools so the model decides when to
  write. Memory writes are AMBER — always visible.
- Don't build a knowledge graph. Semantic search over the last N conversations covers
  95% of what "it remembers me" actually feels like.

---

## 6. Milestones

### M0 — Weekend 1: alive in Claude Desktop
`uv init`, `mcp` SDK, FastMCP server with four tools: `system_status`, `search_files`,
`open_app`, `run_shortcut`. Register in Claude Desktop's MCP config. Test with MCP
Inspector.
**Done when:** "What's my battery and open Spotify" works in Claude Desktop.
*This is the entire MCP half of the goal, finished in two days.*

### M1 — Week 2: your own loop
`core/agent.py` — Anthropic SDK, `tool_runner`, MCP tools via `async_mcp_tool`. CLI REPL
with a personality system prompt + `profile.md`.
**Done when:** `jarvis` in your terminal does everything Claude Desktop did.

### M2 — Week 3: hybrid + policy
Ollama router (tiers 0/1). Permission tiers + audit log wired through every tool.
**Done when:** `volume 40` never touches the API; `plan my week` does.

### M3 — Week 4: memory
sqlite-vec, `remember`/`recall`, profile injection.
**Done when:** it recalls something from three days ago unprompted-but-relevantly.

### M4 — Weeks 5–6: depth
Calendar, Notes, Mail, browser control, clipboard, screenshot + vision. Gated `shell`.
**Done when:** you use it daily without thinking about it.

### M5 — Week 7: always-on
launchd daemon + global hotkey (`skhd`, or a ~100-line Swift menu-bar app).
**Done when:** ⌥Space from anywhere, answer in under a second.

### M6 — Weeks 8–10: voice
- Wake word: **openWakeWord** (a "jarvis" model already exists) or Porcupine.
- VAD: **silero-vad** — this is what tells you when you stopped talking.
- STT: **mlx-whisper** (fast on Apple Silicon) or whisper.cpp.
- TTS: start with macOS `say -v` (free, instant), upgrade to Piper if you want it to
  sound good.
- Barge-in: wake word during playback kills TTS immediately. Non-negotiable for feel.

### M7 — ongoing: proactivity
Scheduled checks that speak only when they have something worth saying. "Meeting in 10
minutes and you haven't opened the doc." This is what separates a Jarvis from a chatbot —
and also what makes it insufferable if you get the threshold wrong. Start extremely
conservative.

---

## 7. Stack

```
python 3.12 · uv
mcp                              # official SDK (FastMCP)
anthropic[mcp]                   # Claude + MCP tool conversion
ollama  → qwen3:4b, nomic-embed-text
pyobjc-framework-{Cocoa,EventKit,CoreWLAN}
sqlite-vec · typer · textual
# M6: mlx-whisper · openWakeWord · silero-vad
```

---

## 8. Traps

1. **Don't start with voice.** Wake-word and STT debugging will burn your motivation
   before you have a brain worth talking to. Text first is not a compromise, it's the
   correct order.
2. **Don't build a framework.** Build five tools you personally use every day. A generic
   plugin architecture with two plugins is a waste of a month.
3. **Tool descriptions are the prompt engineering.** Accuracy comes from precise
   docstrings on each tool, not from a longer system prompt. Spend your effort there.
4. **A changing tool list destroys your prompt cache** every single request. Freeze it.
5. **Never `bash` early.** See §3.
6. **Log everything from commit one.** Retrofitting an audit log is miserable.

---

## 9. First step

```bash
mkdir jarvis && cd jarvis && uv init
uv add "mcp[cli]" "anthropic[mcp]"
# write mcp_server/server.py with ONE tool: system_status()
uv run mcp dev mcp_server/server.py     # opens MCP Inspector
```

Get one tool working end-to-end in the Inspector before writing the second. The first
tool is 80% of the setup cost; tools 2–20 are ten minutes each.
