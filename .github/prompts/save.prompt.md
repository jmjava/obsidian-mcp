---
description: Save the current working context as an Obsidian note
agent: agent
argument-hint: what to save
---

Park the current useful context with the `obsidian-dev-memory` MCP `capture_note` tool.

Prefer the user's text after this command. If they only said "save this", write a concise note covering what we are doing and the detail to keep. Do not paste large files or diffs.

Infer `project` from the workspace folder name unless the user names a project. If they also asked to remember a follow-up action, call `add_todo`. Never persist secrets.
