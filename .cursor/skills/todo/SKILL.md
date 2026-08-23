---
name: todo
description: Add a don't-forget checkbox after asking whether it is repo-scoped or global. Use for /todo when the user has not already chosen a scope.
---

# /todo

Add an open checkbox with the `obsidian-dev-memory` MCP `add_todo` tool.

## Ask for scope first

Unless the user already chose a scope in this message, ask one question:

- **This GitHub repo** — stored under `AI Memory/Projects/<owner-repo>/Todos.md`
- **Global** — stored under `AI Memory/Todos.md` and visible across projects

Do not add the todo until they answer. If they already said "repo", "this repo", "global", or used a shortcut, do not ask.

## After they choose

1. Use the text after `/todo` as the item. Write it as a future action.
2. Call `add_todo` with `scope` set to `repo` or `global`.
3. For repo scope, pass `repository_path` as the workspace root so the GitHub remote can be detected. If there is no GitHub remote, pass `project` from the folder name.
4. Reply with scope, GitHub repo if known, and the vault path.

## Shortcuts that skip this prompt

- `/todo-repo` or `/rtodo` — this GitHub repo
- `/todo-global` or `/gtodo` — global list

## Do not

- Persist secrets.
- Guess the scope when `/todo` is used alone.
