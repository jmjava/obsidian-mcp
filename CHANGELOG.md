# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Added

- Optional task-queue tools: `list_open_tasks`, `claim_task`, and `complete_task`.
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
