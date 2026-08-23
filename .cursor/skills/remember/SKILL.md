---
name: remember
description: Remember something for later in the Obsidian todo list. Use when the user types /remember or says "don't forget this later".
---

# /remember

Store a don't-forget-this-later reminder as an open checkbox in the project `Todos.md`.

## What to remember

Use the text after `/remember`. If the user said "don't forget this" without extra text, turn the current point into one concrete reminder.

## How to save it

1. Infer `project` from the workspace folder name unless the user names a project.
2. Call `add_todo`.
3. If the reminder also needs prose context, call `capture_note` with a one-line explanation.
4. Reply with the saved todo path.

## Later lookup

Call `list_todos` or `get_project_context` at the start of later work so the reminder actually comes back.

## Do not

- Persist secrets.
- Create a full decision note unless the user asked for an architecture decision.
