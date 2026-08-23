---
description: Remember something for later in the Obsidian todo list
agent: agent
argument-hint: what not to forget
---

Store a don't-forget-this-later reminder with the `obsidian-dev-memory` MCP `add_todo` tool.

Use the text after this command. If the user said "don't forget this" without extra text, turn the current point into one concrete reminder.

Infer `project` from the workspace folder name unless the user names a project. If prose context is needed, also call `capture_note`. Reply with the saved path. Never persist secrets.
