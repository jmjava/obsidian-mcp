---
description: Add a todo after asking repo vs global scope
agent: agent
argument-hint: follow-up to track
---

Add an open checkbox with `add_todo`.

If the user did not already choose a scope, ask one question first: this GitHub repo, or global? Do not save until they answer.

Then call `add_todo` with `scope` `repo` or `global`. For repo scope, pass `repository_path` as the workspace root.

Shortcuts that skip the prompt: `/todo-repo`, `/todo-global`, `/rtodo`, `/gtodo`. Never persist secrets.
