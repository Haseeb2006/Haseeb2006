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
uv run mcp dev mcp_server/server.py     # MCP Inspector (needs node)
uv run jarvis-mcp                       # raw stdio server
```

## Wire into Claude Desktop

Copy the block from `claude_desktop_config.example.json` into
`~/Library/Application Support/Claude/claude_desktop_config.json`, replacing
`/ABSOLUTE/PATH/TO/jarvis` with this directory's real path. Restart Claude Desktop.

## Tools

| Tool | Tier | Does |
|---|---|---|
| `system_status` | GREEN | battery, wifi, volume, disk, uptime, frontmost app |
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
