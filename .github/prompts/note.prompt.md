---
description: Save a quick note to the Obsidian vault
agent: agent
argument-hint: what to note
---

Save a short working note with the `obsidian-dev-memory` MCP `capture_note` tool.

Use the text after this command as the note body. If none was given, summarize the current selection or last useful point in one or two sentences.

Infer `project` from the workspace folder name unless the user names a project. Reply with the vault-relative path. Never persist secrets, tokens, keys, or `.env` contents.
