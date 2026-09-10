# jarvis-mcp

A macOS MCP server — the tool layer ("the hands") for a personal assistant.

Written once, used by two clients: Claude Desktop / Claude Code today, and your own
agent loop later. See [`../docs/jarvis-plan.md`](../docs/jarvis-plan.md) for the full plan.

## Install

```bash
uv sync
```

## Run

```bash
uv run jarvis                           # the assistant (needs ANTHROPIC_API_KEY)
uv run mcp dev mcp_server/server.py     # MCP Inspector (needs node)
uv run jarvis-mcp                       # raw stdio server
```

## Tiers

Every message goes to the cheapest tier that can actually handle it:

| Tier | Handles | Cost |
|---|---|---|
| **0 — rules** | `battery`, `volume up`, `mute`/`unmute`, `play`/`pause`, `open`/`close X`, `wifi off`, `dark mode`, `lock`, `find resume` | free, instant |
| **1 — Ollama** | general questions, small talk | free, local |
| **2 — Claude** | anything multi-step, ambiguous, or reasoned | paid |

Escalation is one-way; each reply is tagged with the tier that produced it.

**It runs with no API key at all.** Tiers 0 and 1 need nothing but your Mac:

```bash
brew install ollama && ollama serve
ollama pull qwen3:4b
uv run jarvis           # no ANTHROPIC_API_KEY needed
```

Two rules keep the cheap tiers honest. A tier-0 pattern must match the *whole*
message, so "open Music" acts but "should I open Music?" does not — and if the
call fails anyway ("open the pod bay doors"), the message escalates instead of
returning a confusing error. And anything mentioning this Mac skips the local
model entirely: a model with no tools would answer from imagination.

RED tools are unreachable from tier 0 by construction. Running a Shortcut always
goes through a model and a confirmation.

## Always on

A resident daemon holds the MCP connection, the local model and the conversation
open, so a keystroke gets an answer instead of paying for a cold start each time.

```bash
uv run python install_agent.py     # launchd keeps it running, and restarts it
uv run python install_agent.py --status
uv run python install_agent.py --uninstall
```

**launchd gives a daemon none of your shell environment**, so nothing exported in
`.zshrc` reaches it. Settings go in `~/.jarvis/env` (written for you on install,
mode 0600 since it holds a key):

```
ANTHROPIC_API_KEY=sk-ant-...
JARVIS_ALLOWED_ROOTS=/Users/YOU/Documents,/Users/YOU/Desktop
```

Then from anywhere:

```bash
jarvis-ask battery          # ~100ms, most of it Python starting up
jarvis-ask volume 40
```

### A key that summons it

`jarvis-prompt` opens a native input box, asks, and shows the answer — no extra
software. Bind it to ⌥Space either way:

**Shortcuts app** — nothing to install, and the recommended route:

1. Shortcuts → **+** → search for **Run Shell Script**, add it.
2. Shell: `/bin/zsh`, Pass input: **to stdin**, and as the script:
   `<your uv path> --directory <this folder> run jarvis-prompt`
   (`which uv` gives the first path; use absolute paths — a Shortcut does not
   get your shell's PATH, the same reason the launchd agent needs ~/.jarvis/env.)
3. Name it **Jarvis**, then in the sidebar ⓘ → **Add Keyboard Shortcut** → ⌥Space.

**skhd** is the alternative, but it is not in homebrew-core and needs
Accessibility permission and a background service of its own:

```bash
brew tap koekeishiya/formulae && brew install skhd
skhd --start-service
```

then in `~/.skhdrc`:

```
alt - space : <your uv path> --directory <this folder> run jarvis-prompt
```

The daemon talks over a Unix socket at `~/.jarvis/jarvis.sock`, mode 0600 — not a
TCP port. This process reads files, controls apps and spends money, so
filesystem permissions are the access control and nothing is reachable from the
network. Requests are handled one at a time: there is one machine and one
conversation, and two prompts racing to set the volume is not a feature.

A conversation idle for 30 minutes starts fresh, so yesterday's topic does not
colour today's answer. `JARVIS_IDLE_RESET` changes that.

## Memory

It remembers across sessions, in `~/.jarvis/memory.db` (owner-readable only).

```
› remember that my thesis is due in April
Remembered: my thesis is due in April
  [direct]

› what do you remember
1 fact:
  [1] my thesis is due in April
  [direct]
```

Two searches run on every recall, because either alone has a hole: keyword
search cannot connect "what music do I use" to "prefers Apple Music", and
semantic search cannot reliably find a literal string like `budget.xlsx`. A
memory found both ways ranks above one found either way.

Embeddings come from Ollama (`nomic-embed-text`) when it is there. Without it,
recall falls back to keyword search — worse, not broken.

Recalled memories are injected into the *user turn*, never the system prompt:
what gets recalled changes every message, and a varying system prompt would
invalidate the cached prefix on every request.

`forget` really deletes — row and search index both. A memory you asked it to
drop that turns out to still be there is worse than one never stored, so there
is no quiet soft-delete pretending otherwise. It is RED and asks first.

```bash
ollama pull nomic-embed-text     # optional: recall by meaning
```

## The assistant

`uv run jarvis` is the same five tools, driven by Claude in your terminal instead
of Claude Desktop. It launches the MCP server itself — nothing to configure.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uv run jarvis
```

Commands: `/tools`, `/reset`, `/quit`. Each tool call prints as it runs, so the
machine is never a black box.

RED actions prompt right in the terminal — the server asks the client to confirm,
and this client asks you. Only an explicit `y` runs one.

| Env var | Default | |
|---|---|---|
| `JARVIS_MODEL` | `claude-opus-5` | |
| `JARVIS_EFFORT` | `low` | cost/quality dial: `low` for chat, `high` for planning |
| `JARVIS_MAX_ITERATIONS` | `12` | ceiling on tool calls in one turn |
| `JARVIS_LOCAL_MODEL` | `qwen3:4b` | the Ollama model for tier 1 |
| `OLLAMA_HOST` | `http://localhost:11434` | |

## Wire into Claude Desktop

```bash
uv run python doctor.py --fix    # writes the config, backing up any existing one
```

Then quit Claude Desktop with **Cmd-Q** — closing the window does not reload the
config — and reopen it. `Settings > Developer` should list `jarvis` as running.

`doctor.py` with no arguments checks without changing anything: that the config
parses, names a `uv` that exists, points at this checkout, and — the part nothing
else verifies — that the exact command Claude Desktop will run really does start a
server that answers with all five tools.

Local MCP servers work in the Claude **desktop app** only. claude.ai in a browser
cannot reach a server on your machine.

## Tools

Basics come in pairs, so both directions are equally cheap.

| Tool | Tier | |
|---|---|---|
| `system_status` | GREEN | battery, volume, mute, wifi, dark mode, disk, uptime, frontmost app |
| `search_files` | GREEN | Spotlight search, confined to allowlisted roots |
| `list_shortcuts` | GREEN | names of your Shortcuts |
| `now_playing` | GREEN | what Apple Music is playing |
| `read_clipboard` | GREEN | current clipboard text |
| `open_app` / `quit_app` | AMBER | launch / quit an application |
| `set_volume` / `change_volume` | AMBER | absolute / relative volume |
| `set_mute` | AMBER | mute and unmute (restores the previous level) |
| `set_wifi` | AMBER | Wi-Fi on and off |
| `set_dark_mode` | AMBER | dark and light appearance |
| `media_control` | AMBER | play, pause, next, previous |
| `write_clipboard` | AMBER | replace the clipboard |
| `lock_screen` | AMBER | lock — there is no unlock, by design |
| `recall` / `list_memories` | GREEN | search and list what is remembered |
| `remember` | AMBER | store a durable fact |
| `forget` | RED | delete a memory, for good |
| `run_shortcut` | RED | run a Shortcut (the entitlement bypass) |

Toggles take a boolean rather than splitting into two tools: one tool with a
state cannot drift out of sync the way `wifi_on` and `wifi_off` could.

## Permission tiers

- **GREEN** — read-only. Runs.
- **AMBER** — reversible write. Runs, and is written to the audit log.
- **RED** — destructive or outbound. **Refused** unless explicitly allowlisted, because
  an MCP server cannot prompt you. Allowlist per-item, not globally:

  ```bash
  export JARVIS_ALLOWED_SHORTCUTS="Morning Briefing,Set Focus"
  ```

Every call — allowed, refused, or failed — lands in `~/.jarvis/audit.jsonl`.

## Configuration

| Env var | Default |
|---|---|
| `JARVIS_ALLOWED_ROOTS` | `~/Documents`, `~/Desktop`, `~/Downloads`, `~/Projects` |
| `JARVIS_ALLOWED_SHORTCUTS` | *(empty — all shortcuts refused)* |
| `JARVIS_AUDIT_LOG` | `~/.jarvis/audit.jsonl` |

## Tests

```bash
uv run pytest                             # 258 tests, any platform
uv run python selftest.py                 # exercise every tool on this Mac
uv run python selftest.py --disruptive    # also playback and app launching
```

`pytest` fakes the macOS shell-outs so it runs anywhere. `selftest.py` runs the
real ones and reports what works — read-only tools run freely, reversible ones
are restored to the state they were in, and anything that would interrupt you
needs `--disruptive`. `run_shortcut` is never exercised automatically: it is RED
and could send a message.
