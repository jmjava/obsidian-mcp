# Changelog

All notable changes to this project are documented in this file.

## 0.1.1 - 2026-08-23

### Added

- Slash commands / skills: `/note`, `/save`, `/todo`, `/remember`.
- MCP tools `capture_note`, `add_todo`, `list_todos`, and `search_notes`.
- Project `Notes/YYYY-MM-DD.md` and checkbox `Todos.md` files.
- `get_project_context` now returns `open_todos` so parked reminders come back.

## 0.1.0 - 2026-08-22

### Added

- Local MCP stdio server that stores engineering memory as ordinary Markdown in an Obsidian vault.
- Tools: `get_project_context`, `capture_work_session`, `record_decision`, `update_project_state`, `search_memory`, `read_note`, `append_daily_note`.
- Vault path confinement, symlink-escape checks, and atomic writes.
- Optional Git context capture for work sessions.
- Cursor and GitHub Copilot / VS Code configuration examples.
- Project installer and smoke-test scripts.
