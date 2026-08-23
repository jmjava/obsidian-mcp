---
description: Add a don't-forget checkbox to the Obsidian todo list
agent: agent
argument-hint: follow-up to track
---

Add an open checkbox with the `obsidian-dev-memory` MCP `add_todo` tool.

Use the text after this command as the item. Write it as a future action. Infer `project` from the workspace folder name unless the user names a project.

Reply with the vault path and checkbox text. Later work should call `list_todos` or `get_project_context` so the item is not forgotten. Never persist secrets.
