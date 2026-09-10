# Obsidian Developer Memory MCP

A local [Model Context Protocol](https://modelcontextprotocol.io) server that gives AI coding assistants such as **Cursor**, **GitHub Copilot**, and **Claude** persistent engineering memory.

Memory is stored as ordinary Markdown files in an Obsidian vault. Obsidian does not need to be running. There is no community plugin and no Obsidian API key.

The same stdio MCP server works with Cursor, GitHub Copilot / VS Code, Claude Code, and Claude Desktop.

## Architecture

```text
Cursor Agent --------------------\
                                  \
GitHub Copilot / VS Code -------- > MCP stdio server
                                  /        |
Claude Code / Claude Desktop ----/         v
                               obsidian-dev-memory
                                        |
                                        v
                               Obsidian Markdown Vault
```

```text
Developer opens spring-auth in Cursor, VS Code, or Claude Code
        |
        v
Cursor calls get_project_context("spring-auth")
        |
        v
AI sees current project state + recent decisions
        |
        v
Developer and AI implement feature
        |
        v
AI calls capture_work_session(...)
        |
        +--> session note
        |
        +--> Git branch/SHA recorded
        |
        v
Durable architecture choice?
        |
       yes
        |
        v
record_decision(...)
```

## Why direct Markdown?

The vault is the source of truth. Notes remain readable and editable in Obsidian, git, or any text editor. The server never depends on Obsidian being open, never talks to a hosted memory API, and never writes a proprietary database.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- A local Obsidian vault directory
- Git on `PATH` only if you want automatic repository snapshots

## Installation

```bash
git clone https://github.com/jmjava/obsidian-mcp.git
cd obsidian-mcp
uv sync
```

`uv sync` installs the official MCP Python SDK and the project package.

## Configuration

Required:

```bash
export OBSIDIAN_VAULT_PATH="$HOME/Documents/ObsidianVault"
```

Optional:

```bash
export OBSIDIAN_MEMORY_ROOT="AI Memory"
```

`OBSIDIAN_MEMORY_ROOT` defaults to `AI Memory`. Editor MCP configuration can supply these variables directly. This project includes `.env.example` for documentation; the server does not automatically load `.env` files.

## Running the server

```bash
export OBSIDIAN_VAULT_PATH="/tmp/example-vault"
mkdir -p "$OBSIDIAN_VAULT_PATH"

uv run python -m obsidian_dev_memory
```

or:

```bash
uv run obsidian-dev-memory
```

The process speaks MCP over stdio. Do not write application logs to stdout; diagnostics go to stderr.

## Cursor setup

Project-level Cursor config lives at `.cursor/mcp.json` and uses the current `mcpServers` format. A portable template is in `config/cursor.mcp.json.example`:

```json
{
  "mcpServers": {
    "obsidian-dev-memory": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "--directory",
        "/ABSOLUTE/PATH/TO/obsidian-dev-memory-mcp",
        "run",
        "python",
        "-m",
        "obsidian_dev_memory"
      ],
      "env": {
        "OBSIDIAN_VAULT_PATH": "/ABSOLUTE/PATH/TO/OBSIDIAN/VAULT"
      }
    }
  }
}
```

This repository also ships `.cursor/rules/obsidian-memory.mdc`, which tells Cursor when to read and write memory.

Machine-specific `.cursor/mcp.json` files are created by the installer and are not committed here.

## GitHub Copilot / VS Code setup

Workspace Copilot / VS Code config lives at `.vscode/mcp.json` and uses the current `servers` format. A portable template is in `config/vscode.mcp.json.example`:

```json
{
  "servers": {
    "obsidian-dev-memory": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "--directory",
        "/ABSOLUTE/PATH/TO/obsidian-dev-memory-mcp",
        "run",
        "python",
        "-m",
        "obsidian_dev_memory"
      ],
      "env": {
        "OBSIDIAN_VAULT_PATH": "/ABSOLUTE/PATH/TO/OBSIDIAN/VAULT"
      }
    }
  }
}
```

`.github/copilot-instructions.md` gives Copilot the same memory behavior as Cursor.

## Claude Code setup

Project-level Claude Code config lives at `.mcp.json` and uses the same `mcpServers` format as Cursor. A portable template is in `config/claude.mcp.json.example`:

```json
{
  "mcpServers": {
    "obsidian-dev-memory": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "--directory",
        "/ABSOLUTE/PATH/TO/obsidian-dev-memory-mcp",
        "run",
        "python",
        "-m",
        "obsidian_dev_memory"
      ],
      "env": {
        "OBSIDIAN_VAULT_PATH": "/ABSOLUTE/PATH/TO/OBSIDIAN/VAULT"
      }
    }
  }
}
```

`.claude/rules/obsidian-memory.md` gives Claude Code the same memory behavior as Cursor and Copilot. The installer writes that rule file instead of overwriting an existing `CLAUDE.md`.

Machine-specific `.mcp.json` files are created by the installer and are not committed here. Claude Code may ask you to approve the project server on first use.

Alternatively, add the server from Claude Code:

```bash
claude mcp add --scope project --transport stdio \
  --env OBSIDIAN_VAULT_PATH=/ABSOLUTE/PATH/TO/OBSIDIAN/VAULT \
  obsidian-dev-memory -- \
  uv --directory /ABSOLUTE/PATH/TO/obsidian-dev-memory-mcp \
  run python -m obsidian_dev_memory
```

## Claude Desktop setup

Claude Desktop reads a user-level `mcpServers` file rather than project config:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

Merge the same server entry from `config/claude.mcp.json.example` into that file, then restart Claude Desktop.

## Installer usage

Wire this server into another development project:

```bash
./scripts/install-project.sh \
  --project /home/user/src/example \
  --vault /home/user/Documents/ObsidianVault
```

Optional:

```bash
./scripts/install-project.sh \
  --project /home/user/src/example \
  --vault /home/user/Documents/ObsidianVault \
  --server /path/to/obsidian-dev-memory-mcp
```

If `--server` is omitted, the script infers this repository from its own location.

The installer creates or updates:

- `<project>/.cursor/mcp.json`
- `<project>/.cursor/rules/obsidian-memory.mdc`
- `<project>/.vscode/mcp.json`
- `<project>/.github/copilot-instructions.md`
- `<project>/.mcp.json`
- `<project>/.claude/rules/obsidian-memory.md`

It fails clearly when the target project or vault is missing, and it merges MCP JSON so unrelated servers are not destroyed.

## MCP tools

| Tool | Purpose |
| --- | --- |
| `get_project_context` | Read `Project State.md` plus the newest session and decision notes |
| `capture_work_session` | Append a timestamped section to today's session note |
| `record_decision` | Write a durable decision note |
| `update_project_state` | Replace the concise project-state note |
| `list_open_tasks` | Scan Project State Next Steps plus optional `Agent Queue.md` checkboxes |
| `claim_task` | Move a Next Steps or Agent Queue item to In Progress; check a matching queue box |
| `complete_task` | Move an In Progress or Agent Queue item to Completed; check a matching queue box |
| `block_task` | Move a Next Steps or In Progress item to Blocked |
| `search_memory` | Local filename and text search over project memory |
| `read_note` | Read one vault-relative Markdown file |
| `append_daily_note` | Append to `Daily/YYYY-MM-DD.md` |

`get_project_context` returns empty sections when a project is new instead of failing.

`record_decision` writes `YYYY-MM-DD-<decision-slug>.md`. If that file already exists, the server adds a numeric suffix (`-2`, `-3`, ...) instead of overwriting.

`capture_work_session` accepts an optional `repository_path`. When that path is a Git repository, the note records repository name, branch, short SHA, dirty state, and a short changed-file list. Full diffs are never written. A non-Git path is ignored.

`list_open_tasks` returns Next Steps bullets and, when `AI Memory/Agent Queue.md` exists, unchecked `- [ ]` lines. `claim_task` / `complete_task` parse the current Project State, move one matching Next Steps or In Progress bullet (or a unique Agent Queue item when Project State has no match), and rewrite the note through `update_project_state` so other sections are preserved. When a unique unchecked Agent Queue checkbox matches, that line is checked in place; other queue lines stay put. `block_task` moves one matching Next Steps or In Progress bullet to Blocked through the same rewrite path and does not check Agent Queue boxes. They do not write daily notes. Match by exact text or a unique substring.

## Vault layout

```text
AI Memory/
├── Agent Queue.md          # optional shared checkbox list; claim/complete may check a match
└── Projects/
    └── <project-slug>/
        ├── Project State.md
        ├── Sessions/
        │   └── YYYY-MM-DD.md
        └── Decisions/
            └── YYYY-MM-DD-<decision-slug>.md

Daily/
└── YYYY-MM-DD.md
```

The `AI Memory` folder honors `OBSIDIAN_MEMORY_ROOT`. Logical project names are slugified (`Spring Authorization Server` → `spring-authorization-server`).

## Example workflow

1. Open a project in Cursor, VS Code, or Claude Code.
2. Before substantial work, the assistant calls `get_project_context`.
3. After meaningful implementation, it calls `capture_work_session`.
4. When an architecture choice is made, it calls `record_decision`.
5. When overall status changes, it calls `update_project_state`.
6. Open the vault in Obsidian at any time to read or edit the same files.

## Security model

- All note paths must resolve inside `OBSIDIAN_VAULT_PATH`.
- Absolute note paths, `../` traversal, and detectable symlink escapes are rejected.
- Writes are atomic (`tempfile` + `os.replace`) where practical.
- The tools are not a general filesystem API.
- Secret-looking values (keys, tokens, JWTs, private keys, `password=` assignments) are replaced with `[redacted-secret]` before they are written.
- Cursor rules, Copilot instructions, and Claude Code rules tell the assistant never to persist passwords, API keys, tokens, JWTs, private keys, `.env` contents, database credentials, production secrets, or sensitive customer data.

## Testing

Tests use temporary directories, never your real vault.

```bash
uv run pytest
```

A broader local check:

```bash
export OBSIDIAN_VAULT_PATH="$HOME/Documents/ObsidianVault"
./scripts/smoke-test.sh
```

The smoke test verifies the environment variable, vault directory, package import, server construction, and the pytest suite.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Server exits immediately | `OBSIDIAN_VAULT_PATH` is set and the directory exists |
| Tools do not appear in Cursor | Project `.cursor/mcp.json` is present; reload the window; `uv` is on PATH |
| Tools do not appear in Copilot | Workspace `.vscode/mcp.json` uses a top-level `servers` key, not `mcpServers` |
| Tools do not appear in Claude Code | Project `.mcp.json` uses a top-level `mcpServers` key; approve the server if prompted; `uv` is on PATH |
| Tools do not appear in Claude Desktop | The user-level `claude_desktop_config.json` includes the `mcpServers` entry; restart Claude Desktop |
| `Path traversal is not allowed` | Pass vault-relative paths such as `AI Memory/Projects/spring-auth/Project State.md` |
| Decision file name already existed | The server wrote `YYYY-MM-DD-<slug>-2.md` instead of overwriting |
| Git section missing from a session | `repository_path` was omitted or is not a Git repository; that is non-fatal |
| Unexpected stdout noise | Only MCP JSON-RPC should use stdout; logs belong on stderr |

## License

MIT. See [LICENSE](LICENSE).
