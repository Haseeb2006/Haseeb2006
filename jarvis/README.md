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
| **0 — rules** | `volume 40`, `battery`, `open Music`, `find resume` | free, instant |
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

| Tool | Tier | Does |
|---|---|---|
| `system_status` | GREEN | battery, wifi, volume, disk, uptime, frontmost app |
| `set_volume` | AMBER | set output volume 0-100 |
| `search_files` | GREEN | Spotlight search, confined to allowlisted roots |
| `open_app` | AMBER | launch a Mac application by name |
| `list_shortcuts` | GREEN | names of your Shortcuts |
| `run_shortcut` | RED | run a Shortcut by name (the entitlement bypass) |

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
uv run pytest
```

Tests run on any platform — the macOS shell-outs are faked.
