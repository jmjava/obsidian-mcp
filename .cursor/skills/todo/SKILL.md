---
name: todo
description: Add a don't-forget-later checkbox to the project Obsidian todo list. Use when the user types /todo or asks to track a follow-up.
---

# /todo

Add an open checkbox to `Todos.md` in the Obsidian vault.

## What to capture

Use the text after `/todo` as the item. If the user did not specify the item, infer one follow-up from the current conversation and confirm it in the tool call.

Write the item as a future action, for example "Verify refresh-token flow", not a status report.

## How to save it

1. Infer `project` from the workspace folder name unless the user names a project.
2. Call `add_todo`.
3. Reply with the vault-relative path and the new checkbox text.

## Later lookup

Agents should call `list_todos` or `search_notes` before guessing about open follow-ups. `get_project_context` also returns `open_todos`.

## Do not

- Persist secrets.
- Mark items done here. The user can check the box in Obsidian.
