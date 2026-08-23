---
name: todo-repo
description: Add a repo-scoped Obsidian todo without asking. Use for /todo-repo when the user wants this GitHub repository only.
---

# /todo-repo

Add an open checkbox with `add_todo` and `scope="repo"`. Do not ask about scope.

1. Use the text after the command as the item.
2. Pass `repository_path` as the workspace root so the GitHub `owner/repo` remote is used.
3. If there is no GitHub remote, pass `project` from the folder name.
4. Reply with the repo identity and vault path. Never persist secrets.
