# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Added

- `list_open_tasks` includes top-level `TODO/*.md` notes with frontmatter `status: open` or unchecked items. `claim_task` / `complete_task` can match a unique TODO note without creating `Agent Queue.md`.
- Optional task-queue tools: `list_open_tasks`, `list_blocked_tasks`, `claim_task`, `complete_task`, `block_task`, and `unblock_task`.
- `claim_task` / `complete_task` check a unique matching `AI Memory/Agent Queue.md` checkbox in place.
- `block_task` moves one Next Steps or In Progress bullet to Blocked through `update_project_state`.
- `list_blocked_tasks` lists Blocked / Blockers bullets without rewriting Project State or daily notes.
- `unblock_task` moves one Blocked / Blockers bullet back to Next Steps through `update_project_state`.
- Claude Code project setup: `.mcp.json` example, `.claude/rules/obsidian-memory.md`, and installer support.
- Claude Desktop configuration notes that reuse the same `mcpServers` stdio entry.

## 0.1.0 - 2026-08-22

### Added

- Local MCP stdio server that stores engineering memory as ordinary Markdown in an Obsidian vault.
- Tools: `get_project_context`, `capture_work_session`, `record_decision`, `update_project_state`, `search_memory`, `read_note`, `append_daily_note`.
- Vault path confinement, symlink-escape checks, and atomic writes.
- Optional Git context capture for work sessions.
- Cursor and GitHub Copilot / VS Code configuration examples.
- Project installer and smoke-test scripts.
