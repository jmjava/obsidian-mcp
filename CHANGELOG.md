# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Fixed

- `append_daily_note` / `append_under_heading` require a unique heading title. `heading="Usage"` will not splice under a burn-plan Usage at the top when a later Usage exists. Concurrent daily appends take an exclusive lock outside the vault.
- `claim_task` / `complete_task` treat substring matches as one canonical task across Project State, Agent Queue, and TODO. A short query such as `docs` cannot complete `Write docs` and check a different queue line; queue sync uses the matched item text, not the raw query. Concurrent claim/complete/block/unblock calls for the same project take an exclusive lock outside the vault.
- `claim_task` / `complete_task` no longer fail-open on Agent Queue sync: a missing queue is reported as unchecked (the file is never invented), an ambiguous queue match raises before any write, and a unique checkbox is written before Project State so a claim cannot succeed while leaving the box open.
- `read_note`, `get_project_context`, and `search_memory` redact secret-looking values in returned text. Vault files are not rewritten on read.
- `redact_secrets` now matches unlabeled `scheme://user:pass@host` connection strings (and `pwd=` / `passwd=` assignments) on write and read.
- `update_project_state` merges a patch instead of rebuilding the note: omitted fields keep existing sections, `blocked=[]` clears Blocked only, and unknown H2 sections survive. `parse_project_state` keeps custom H2s as `extra_sections` so task-tool rewrites do not drop them.

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
