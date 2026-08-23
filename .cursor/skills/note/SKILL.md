---
name: note
description: Save a quick Obsidian note from the current chat. Use when the user types /note, says "note this", or wants to park a thought for later.
---

# /note

Save a short working note to the Obsidian vault using the `obsidian-dev-memory` MCP tools.

## What to capture

Use the text after `/note` as the note body. If the user said "note this" without extra text, summarize the current selection, open file, or last useful point in one or two sentences.

## How to save it

1. Infer `project` from the workspace folder name unless the user names a project.
2. Call `capture_note` with that project and the note content.
3. Reply with the vault-relative path. Do not dump the whole note back.

## Do not

- Persist secrets, tokens, keys, `.env` contents, or customer data.
- Create a full work-session log. That is `/save` or `capture_work_session`.
- Create a todo checkbox. That is `/todo` or `/remember`.
