# GitHub Copilot: Obsidian Developer Memory

Use the `obsidian-dev-memory` MCP tools to keep durable engineering memory in the local Obsidian vault. The same server is used by Cursor. Obsidian does not need to be running.

## When to read memory

Call `get_project_context` before substantial work when prior project memory is likely to help: continuing a feature, debugging a known area, making an architecture change, or explaining why the code is the way it is.

Do not call it for trivial edits.

Call `search_memory` or `search_notes` before guessing about prior decisions, notes, or reminders. Call `list_todos` so parked follow-ups come back. Use `read_note` only when you already have a vault-relative Markdown path.

Slash commands and prompts:

- `/note` or "note this" → `capture_note`
- `/save` or "save this" → `capture_note`
- `/todo` or `/remember` or "don't forget this later" → ask repo vs global, then `add_todo`
- `/todo-repo` `/rtodo` `/remember-repo` `/rremember` → repo scope, no prompt
- `/todo-global` `/gtodo` `/remember-global` `/gremember` → global scope, no prompt

## When to record sessions

Call `capture_work_session` after meaningful work:

- an implementation
- an investigation
- a debugging session
- a migration
- an architecture change
- a research task

Do not record:

- typo fixes
- formatting-only changes
- trivial comments
- one-line mechanical edits

Prefer updating today's session note over creating duplicate notes.

## When to record decisions

Call `record_decision` for architectural or engineering decisions that future work should know about, such as:

- selected authentication architecture
- changed API boundaries
- selected persistence mechanism
- changed deployment strategy
- chose one library over another for a durable reason

If a decision file with the same generated name already exists, the server adds a numeric suffix instead of overwriting.

## When to update project state

Call `update_project_state` when the overall project state materially changes. Keep `Project State.md` concise. It is not a session log.

## Daily notes

Use `append_daily_note` for short useful items on today's vault daily note. Do not overwrite existing daily-note contents.

## Never store secrets

Never persist passwords, API keys, access tokens, refresh tokens, JWT values, private keys, `.env` contents, database credentials, production secrets, or sensitive customer data.

If a work summary contains secret-looking material, summarize it generically rather than persisting the literal value.
