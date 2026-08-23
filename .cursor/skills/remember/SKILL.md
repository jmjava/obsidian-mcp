---
name: remember
description: Remember something for later after asking repo vs global scope. Use for /remember or "don't forget this later" when scope is not specified.
---

# /remember

Store a don't-forget reminder with `add_todo`.

## Ask for scope first

Unless the user already chose, ask:

- **This GitHub repo**
- **Global** (all work)

Do not save until they answer. Shortcuts that skip the prompt: `/remember-repo`, `/remember-global`, `/rremember`, `/gremember`.

## After they choose

1. Turn their text into one concrete reminder.
2. Call `add_todo` with `scope` `repo` or `global`.
3. For repo scope, pass `repository_path` as the workspace root.
4. Reply with scope and path.

Later work should call `list_todos` with `scope="all"` or use `open_todos` and `global_todos` from `get_project_context`.
