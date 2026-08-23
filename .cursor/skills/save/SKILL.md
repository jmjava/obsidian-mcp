---
name: save
description: Save the current working context as an Obsidian note. Use when the user types /save or says "save this".
---

# /save

Park the current useful context in the Obsidian vault so it can be found later.

## What to save

Prefer the user's text after `/save`. If they only said "save this", write a concise note covering:

- what we are doing
- the important detail to keep
- any file or area it refers to

Keep it short. Do not paste large file contents or diffs.

## How to save it

1. Infer `project` from the workspace folder name unless the user names a project.
2. Call `capture_note`. Add a short `title` when that helps later search.
3. If the user clearly asked to remember a follow-up action, also call `add_todo`.
4. Reply with the saved path.

## Do not

- Persist secrets, tokens, keys, `.env` contents, or customer data.
- Replace `capture_work_session` after a completed implementation. `/save` is a mid-work snapshot.
