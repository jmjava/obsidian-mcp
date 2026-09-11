"""Deterministic Markdown helpers for Obsidian notes."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime

SECRET_PLACEHOLDER = "[redacted-secret]"

_SECRET_PATTERNS = (
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(
        r"\b(?:sk|pk|rk|ghp|gho|ghu|ghs|ghr|github_pat|xox[baprs]|AIza)[-_][A-Za-z0-9._-]{16,}\b"
    ),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|"
        r"refresh[_-]?token|private[_-]?key|db[_-]?password|authorization)"
        r"\s*[:=]\s*\S+"
    ),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-+=/]{16,}"),
    # Unlabeled URI userinfo: postgres://user:pass@host, redis://:pass@host
    re.compile(
        r"(?i)\b(?:jdbc:)?[a-z][a-z0-9+.-]*://"
        r"[^\s/@:]*:[^\s/@]+@[^\s)\]>'`,;]+"
    ),
)

_UNSAFE_SLUG_RE = re.compile(r"[^a-z0-9-]+")
_REPEAT_DASH_RE = re.compile(r"-{2,}")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(\S.*)$")
_BULLET_RE = re.compile(r"^[-*+]\s+(?:\[([ xX])\]\s+)?(.*\S)\s*$")
_CHECKBOX_LINE_RE = re.compile(r"^([-*+][ \t]+)\[([ xX])\]([ \t]+)(.*\S)[ \t]*$")
_LEADING_BULLET_RE = re.compile(r"^[-*+]\s+")
_LEADING_CHECKBOX_RE = re.compile(r"^\[[ xX]\]\s+")
_TRAILING_TASK_META_RE = re.compile(r"(?:\s+#\S+|\s+\[repo::[^\]]+\])$")

_PROSE_FIELDS = {
    "objective": "objective",
    "current state": "current_state",
}
_LIST_FIELDS = {
    "architecture": "architecture",
    "completed": "completed",
    "in progress": "in_progress",
    "blocked": "blocked",
    "blockers": "blocked",
    "next steps": "next_steps",
    "important files": "important_files",
    "notes": "notes",
}
_CANONICAL_TITLES = {
    "objective": "Objective",
    "current_state": "Current State",
    "architecture": "Architecture",
    "completed": "Completed",
    "in_progress": "In Progress",
    "blocked": "Blocked",
    "next_steps": "Next Steps",
    "important_files": "Important Files",
    "notes": "Notes",
}
_KNOWN_FIELD_ORDER = (
    "objective",
    "current_state",
    "architecture",
    "completed",
    "in_progress",
    "blocked",
    "next_steps",
    "important_files",
    "notes",
)


class TaskMatchError(ValueError):
    """Raised when a task query matches zero or more than one bullet."""


class HeadingMatchError(ValueError):
    """Raised when a heading title matches more than one section."""


def slugify(value: str) -> str:
    """Normalize a logical name into a filesystem-safe ASCII slug."""
    text = unicodedata.normalize("NFKD", value)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("_", "-")
    text = re.sub(r"\s+", "-", text)
    text = _UNSAFE_SLUG_RE.sub("", text)
    text = _REPEAT_DASH_RE.sub("-", text).strip("-")
    if not text:
        raise ValueError("Value produced an empty slug")
    return text


def redact_secrets(text: str) -> str:
    """Replace secret-looking material with a generic placeholder."""
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(SECRET_PLACEHOLDER, redacted)
    return redacted


def _yaml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    text = str(value)
    needs_quotes = text == "" or any(ch in text for ch in "#{}[],&*?|>!%@`'\"\n")
    needs_quotes = needs_quotes or text.startswith(" ") or text.endswith(" ")
    needs_quotes = needs_quotes or ": " in text
    if needs_quotes:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def format_frontmatter(fields: Mapping[str, object]) -> str:
    """Render a deterministic YAML frontmatter block."""
    lines = ["---"]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, list):
            if not value:
                continue
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {_yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def local_now(now: datetime | None = None) -> datetime:
    """Return an aware local datetime."""
    if now is None:
        return datetime.now().astimezone()
    if now.tzinfo is None:
        return now.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return now


def format_date(now: datetime | None = None) -> str:
    return local_now(now).strftime("%Y-%m-%d")


def format_iso_datetime(now: datetime | None = None) -> str:
    return local_now(now).isoformat(timespec="seconds")


def format_heading_time(now: datetime | None = None) -> str:
    """Format a session heading time such as ``11:42 EDT``."""
    stamp = local_now(now)
    tz_name = stamp.tzname()
    if not tz_name:
        offset = stamp.strftime("%z")
        tz_name = f"UTC{offset[:3]}:{offset[3:]}" if offset else "local"
    return f"{stamp.strftime('%H:%M')} {tz_name}"


def bullet_list(items: Sequence[str] | None) -> str:
    """Render a Markdown list, omitting empty items and redacting secrets."""
    if not items:
        return ""
    lines: list[str] = []
    for item in items:
        cleaned = redact_secrets(str(item).strip())
        if cleaned:
            lines.append(f"- {cleaned}")
    return "\n".join(lines)


def section(title: str, body: str | Sequence[str] | None, *, level: int = 2) -> str:
    """Render a heading section, or an empty string when the body is empty."""
    if body is None:
        return ""
    if isinstance(body, (list, tuple)):
        rendered = bullet_list(body)
    else:
        rendered = redact_secrets(str(body).strip())
    if not rendered:
        return ""
    hashes = "#" * min(max(level, 1), 6)
    return f"{hashes} {title}\n\n{rendered}"


def join_blocks(*blocks: str) -> str:
    """Join non-empty Markdown blocks with a blank line."""
    parts = [block.strip("\n") for block in blocks if block and block.strip()]
    if not parts:
        return ""
    return "\n\n".join(parts) + "\n"


def heading_level(line: str) -> int | None:
    match = _HEADING_RE.match(line.rstrip())
    return len(match.group(1)) if match else None


def heading_title(line: str) -> str:
    match = _HEADING_RE.match(line.rstrip())
    if not match:
        return line.strip().lower()
    return match.group(2).strip().lower()


def _heading_text(line: str) -> str:
    match = _HEADING_RE.match(line.rstrip())
    if not match:
        return line.strip()
    return match.group(2).strip()


def normalize_heading(heading: str) -> str:
    heading = heading.strip()
    if heading.startswith("#"):
        return heading
    return f"## {heading}"


def extract_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def excerpt_around(text: str, terms: Sequence[str], *, limit: int = 240) -> str:
    """Return a compact excerpt around the first matching term."""
    lowered = text.lower()
    index = -1
    for term in terms:
        found = lowered.find(term.lower())
        if found >= 0 and (index < 0 or found < index):
            index = found
    if index < 0:
        compact = " ".join(text.split())
        return compact[:limit].rstrip()
    start = max(0, index - 80)
    end = min(len(text), index + limit - 80)
    snippet = text[start:end]
    snippet = " ".join(snippet.split())
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


def strip_frontmatter(markdown: str) -> str:
    """Remove a leading YAML frontmatter block when present."""
    split = _split_frontmatter(markdown)
    if split is None:
        return markdown
    _block, body = split
    return body.lstrip("\n")


def _split_frontmatter(markdown: str) -> tuple[str, str] | None:
    """Return ``(frontmatter_block, remainder)`` or ``None`` when absent."""
    if not markdown.startswith("---"):
        return None
    rest = markdown[3:]
    if rest.startswith("\n"):
        rest = rest[1:]
    end = rest.find("\n---")
    if end < 0:
        return None
    return rest[:end], rest[end + 4 :]


def parse_frontmatter_fields(markdown: str) -> dict[str, str]:
    """Parse scalar YAML frontmatter keys. Lists and nested maps are skipped."""
    split = _split_frontmatter(markdown)
    if split is None:
        return {}
    fields: dict[str, str] = {}
    for line in split[0].splitlines():
        if not line or line[0] in {" ", "\t", "-"}:
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
            value = value[1:-1]
        fields[key] = value
    return fields


def set_frontmatter_field(markdown: str, key: str, value: str) -> str:
    """Replace or insert one scalar frontmatter field. Other lines stay put."""
    rendered = f"{key}: {_yaml_scalar(value)}"
    split = _split_frontmatter(markdown)
    if split is None:
        prefix = format_frontmatter({key: value})
        body = markdown if markdown.endswith("\n") or markdown == "" else markdown + "\n"
        if not body:
            return prefix + "\n"
        return prefix + "\n" + body.lstrip("\n")
    block, remainder = split
    lines = block.splitlines()
    key_re = re.compile(rf"^{re.escape(key)}\s*:")
    replaced = False
    updated_lines: list[str] = []
    for line in lines:
        if not replaced and key_re.match(line):
            updated_lines.append(rendered)
            replaced = True
        else:
            updated_lines.append(line)
    if not replaced:
        updated_lines.append(rendered)
    updated = "---\n" + "\n".join(updated_lines) + "\n---" + remainder
    if markdown.endswith("\n") and not updated.endswith("\n"):
        updated += "\n"
    return updated


def parse_open_todo_entries(
    markdown: str,
    fallback_title: str,
    *,
    note_statuses: frozenset[str] | None = None,
) -> list[tuple[str, str]]:
    """Return ``(text, kind)`` for a TODO note and its unchecked items.

    ``kind`` is ``note`` when frontmatter ``status`` is in ``note_statuses``
    (default ``open``), or ``checkbox`` for each unchecked ``- [ ]`` line.
    """
    allowed = note_statuses if note_statuses is not None else frozenset({"open"})
    entries: list[tuple[str, str]] = []
    fields = parse_frontmatter_fields(markdown)
    status = fields.get("status", "").strip().casefold()
    if status in allowed:
        title = extract_title(markdown, fallback_title).strip()
        if title:
            entries.append((title, "note"))
    for item in parse_open_checkboxes(markdown):
        entries.append((item, "checkbox"))
    return entries


def parse_bullets(text: str) -> list[str]:
    """Extract Markdown bullet texts, stripping optional checkbox markers."""
    items: list[str] = []
    for line in text.splitlines():
        match = _BULLET_RE.match(line)
        if not match:
            continue
        item = match.group(2).strip()
        if item:
            items.append(item)
    return items


def parse_open_checkboxes(text: str) -> list[str]:
    """Extract unchecked ``- [ ]`` checkbox items from an Agent Queue note."""
    return [item for _index, _match, item in _iter_open_checkbox_lines(text)]


def _iter_open_checkbox_lines(text: str) -> list[tuple[int, re.Match[str], str]]:
    """Return ``(line_index, match, item_text)`` for unchecked checkbox lines."""
    rows: list[tuple[int, re.Match[str], str]] = []
    for index, line in enumerate(text.splitlines()):
        match = _CHECKBOX_LINE_RE.match(line)
        if match is None:
            continue
        if match.group(2) != " ":
            continue
        item = match.group(4).strip()
        if item:
            rows.append((index, match, item))
    return rows


def move_open_checkbox(
    text: str,
    query: str,
    *,
    canonical: bool = False,
) -> tuple[str, str]:
    """Check the unique matching unchecked Agent Queue checkbox.

    Other lines are preserved. The rewritten line is secret-redacted.
    Returns ``(updated_markdown, matched_item_text)``.

    ``canonical=True`` matches the same task after stripping trailing
    ``#tags`` and ``[repo::...]`` markers. Use that after a claim has
    already resolved the item so a short query cannot check a different
    queue line.
    """
    lines = text.splitlines()
    open_rows = _iter_open_checkbox_lines(text)
    if not open_rows:
        raise TaskMatchError(f"No matching task for {query!r}")
    open_items = [item for _index, _match, item in open_rows]
    if canonical:
        matched = find_canonical_task(open_items, query)
    else:
        matched = find_matching_task(open_items, query)
    hits = [
        row
        for row in open_rows
        if normalize_task_text(row[2]) == normalize_task_text(matched)
    ]
    if len(hits) != 1:
        raise TaskMatchError(f"Ambiguous task match for {query!r}")
    index, match, item = hits[0]
    prefix, _mark, mid, raw_item = match.groups()
    lines[index] = f"{prefix}[x]{mid}{redact_secrets(raw_item.strip())}"
    updated = "\n".join(lines)
    if text.endswith("\n"):
        updated += "\n"
    return updated, redact_secrets(item)


def parse_project_state(
    markdown: str,
) -> dict[str, str | list[str] | list[tuple[str, str]]]:
    """Parse Project State.md into update_project_state kwargs.

    Known H2s map to the public tool fields. Unknown H2s are kept in
    ``extra_sections`` as ``(title, body)`` pairs so a later rewrite can
    round-trip them.
    """
    parsed: dict[str, str | list[str] | list[tuple[str, str]]] = {
        "objective": "",
        "current_state": "",
        "architecture": [],
        "completed": [],
        "in_progress": [],
        "blocked": [],
        "next_steps": [],
        "important_files": [],
        "notes": [],
        "extra_sections": [],
    }
    extras: list[tuple[str, str]] = []
    for title, body in _iter_level2_sections(markdown):
        lookup = title.lower()
        if lookup in _PROSE_FIELDS:
            parsed[_PROSE_FIELDS[lookup]] = body.strip()
        elif lookup in _LIST_FIELDS:
            key = _LIST_FIELDS[lookup]
            items = parsed[key]
            if isinstance(items, list) and all(isinstance(item, str) for item in items):
                parsed[key] = list(items) + parse_bullets(body)
        else:
            extras.append((title, body.strip()))
    parsed["extra_sections"] = extras
    return parsed


def patch_project_state_sections(
    existing_markdown: str,
    *,
    objective: str | None = None,
    current_state: str | None = None,
    architecture: Sequence[str] | None = None,
    completed: Sequence[str] | None = None,
    in_progress: Sequence[str] | None = None,
    blocked: Sequence[str] | None = None,
    next_steps: Sequence[str] | None = None,
    important_files: Sequence[str] | None = None,
    notes: Sequence[str] | None = None,
    extra_sections: Sequence[tuple[str, str]] | None = None,
) -> list[str]:
    """Merge a Project State patch into rendered H2 blocks.

    ``None`` keeps the existing section. An empty string or empty list
    clears that section. Unknown H2s from the note survive; additional
    ``extra_sections`` are appended when they are not already present.
    """
    provided: dict[str, str | Sequence[str]] = {}
    if objective is not None:
        provided["objective"] = objective
    if current_state is not None:
        provided["current_state"] = current_state
    if architecture is not None:
        provided["architecture"] = architecture
    if completed is not None:
        provided["completed"] = completed
    if in_progress is not None:
        provided["in_progress"] = in_progress
    if blocked is not None:
        provided["blocked"] = blocked
    if next_steps is not None:
        provided["next_steps"] = next_steps
    if important_files is not None:
        provided["important_files"] = important_files
    if notes is not None:
        provided["notes"] = notes

    existing_raw: dict[str, tuple[str, str]] = {}
    extras_after: dict[str | None, list[tuple[str, str]]] = {None: []}
    seen_known: set[str] = set()
    seen_unknown: set[str] = set()
    last_known: str | None = None

    for title, body in _iter_level2_sections(existing_markdown):
        lookup = title.lower()
        if lookup in _PROSE_FIELDS:
            key = _PROSE_FIELDS[lookup]
            last_known = key
            if key in seen_known:
                continue
            seen_known.add(key)
            existing_raw[key] = (title, body)
            continue
        if lookup in _LIST_FIELDS:
            key = _LIST_FIELDS[lookup]
            last_known = key
            if key in seen_known:
                continue
            seen_known.add(key)
            existing_raw[key] = (title, body)
            continue
        if lookup in seen_unknown:
            continue
        seen_unknown.add(lookup)
        extras_after.setdefault(last_known, []).append((title, body))

    blocks: list[str] = []

    def _flush_extras(anchor: str | None) -> None:
        for extra_title, extra_body in extras_after.get(anchor, []):
            rendered_extra = section(extra_title, extra_body)
            if rendered_extra:
                blocks.append(rendered_extra)

    _flush_extras(None)
    for key in _KNOWN_FIELD_ORDER:
        if key in provided:
            rendered = section(_CANONICAL_TITLES[key], provided[key])
        elif key in existing_raw:
            raw_title, raw_body = existing_raw[key]
            rendered = section(raw_title, raw_body)
        else:
            rendered = ""
        if rendered:
            blocks.append(rendered)
        _flush_extras(key)

    if extra_sections:
        for title, body in extra_sections:
            lookup = title.lower()
            if lookup in _PROSE_FIELDS or lookup in _LIST_FIELDS:
                continue
            if lookup in seen_unknown:
                continue
            seen_unknown.add(lookup)
            rendered = section(title, body)
            if rendered:
                blocks.append(rendered)

    return blocks


def _iter_level2_sections(markdown: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        if current_title is not None:
            sections.append((current_title, "\n".join(current_lines).strip()))
        current_title = None
        current_lines = []

    for line in strip_frontmatter(markdown).splitlines():
        level = heading_level(line)
        if level == 1:
            continue
        if level == 2:
            flush()
            current_title = _heading_text(line)
            continue
        if current_title is not None:
            current_lines.append(line)
    flush()
    return sections


def normalize_task_text(value: str) -> str:
    """Normalize a bullet or checkbox line for matching."""
    text = value.strip()
    text = _LEADING_BULLET_RE.sub("", text)
    text = _LEADING_CHECKBOX_RE.sub("", text)
    return " ".join(text.split()).casefold()


def canonical_task_text(value: str) -> str:
    """Normalize task text and strip trailing ``#tags`` / ``[repo::...]``.

    Secrets are redacted first so a Project State rewrite that already
    replaced ``password=...`` still clusters with the raw queue line.
    """
    text = normalize_task_text(redact_secrets(value))
    while True:
        stripped = _TRAILING_TASK_META_RE.sub("", text)
        if stripped == text:
            return text
        text = stripped


def find_canonical_task(items: Sequence[str], query: str) -> str:
    """Return the unique item with the same canonical task text as ``query``."""
    needle = canonical_task_text(query)
    if not needle:
        raise TaskMatchError("task text is required")
    hits = [item for item in items if canonical_task_text(item) == needle]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise TaskMatchError(f"Ambiguous task match for {query!r}")
    raise TaskMatchError(f"No matching task for {query!r}")


def cluster_matching_tasks(
    sources: Sequence[tuple[str, Sequence[str]]],
    query: str,
) -> dict[str, list[tuple[str, str]]]:
    """Group substring matches by canonical task text.

    An exact (normalized or canonical) hit wins over other substring
    groups so ``Write docs`` does not collide with ``Write docs later``.
    """
    needle = normalize_task_text(query)
    if not needle:
        raise TaskMatchError("task text is required")
    grouped: dict[str, list[tuple[str, str]]] = {}
    for name, items in sources:
        for item in items:
            key = normalize_task_text(item)
            if needle != key and needle not in key:
                continue
            grouped.setdefault(canonical_task_text(item), []).append((name, item))
    exact = {
        canon: rows
        for canon, rows in grouped.items()
        if canon == needle
        or any(normalize_task_text(item) == needle for _source, item in rows)
    }
    if exact:
        return exact
    return grouped


def resolve_unique_task(
    sources: Sequence[tuple[str, Sequence[str]]],
    query: str,
    *,
    prefer: Sequence[str],
) -> tuple[str, str]:
    """Return ``(matched_text, source_name)`` for one canonical task.

    Distinct canonical texts that share a substring (``docs`` vs
    ``Write docs`` and ``Fix docs-drift``) are ambiguous, including
    across Project State, Agent Queue, and TODO sources.
    """
    grouped = cluster_matching_tasks(sources, query)
    if not grouped:
        raise TaskMatchError(f"No matching task for {query!r}")
    if len(grouped) > 1:
        raise TaskMatchError(f"Ambiguous task match for {query!r}")
    rows = next(iter(grouped.values()))
    by_source: dict[str, list[str]] = {}
    for source, item in rows:
        by_source.setdefault(source, []).append(item)
    for source in prefer:
        items = by_source.get(source)
        if not items:
            continue
        unique: list[str] = []
        seen: set[str] = set()
        for item in items:
            key = normalize_task_text(item)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        if len(unique) > 1:
            raise TaskMatchError(f"Ambiguous task match for {query!r}")
        return unique[0], source
    raise TaskMatchError(f"No matching task for {query!r}")


def find_matching_task(items: Sequence[str], query: str) -> str:
    """Return the unique item matching ``query`` exactly or as a substring."""
    matched, _source = resolve_unique_task((("items", items),), query, prefer=("items",))
    return matched


def find_task_across_sources(
    sources: Sequence[tuple[str, Sequence[str]]],
    query: str,
) -> tuple[str, str]:
    """Return ``(matched_text, source_name)`` for a unique match across lists."""
    prefer = [name for name, _items in sources]
    return resolve_unique_task(sources, query, prefer=prefer)


def move_task_bullet(
    source: Sequence[str],
    dest: Sequence[str],
    query: str,
) -> tuple[list[str], list[str], str]:
    """Move the unique matching bullet from ``source`` onto ``dest``."""
    matched = find_matching_task(source, query)
    new_source = list(source)
    new_source.remove(matched)
    new_dest = list(dest)
    if not any(normalize_task_text(item) == normalize_task_text(matched) for item in new_dest):
        new_dest.append(matched)
    return new_source, new_dest, matched


def append_under_heading(existing: str, content: str, heading: str | None = None) -> str:
    """Append content under a heading, creating the heading when missing.

    Same-title headings must be unique. ``heading="Usage"`` will not splice
    under a burn-plan Usage at the top when a later Usage exists.
    """
    content = redact_secrets(content.rstrip())
    if not content:
        return existing if existing.endswith("\n") or existing == "" else existing + "\n"

    if not heading:
        if not existing.strip():
            return content + "\n"
        return existing.rstrip() + "\n\n" + content + "\n"

    heading_line = normalize_heading(heading)
    target = heading_title(heading_line)
    level = heading_level(heading_line) or 2
    lines = existing.splitlines()
    matches = [
        index
        for index, line in enumerate(lines)
        if heading_level(line) is not None and heading_title(line) == target
    ]
    if len(matches) > 1:
        raise HeadingMatchError(f"Ambiguous heading match for {heading.strip()!r}")
    if matches:
        index = matches[0]
        end = len(lines)
        for cursor in range(index + 1, len(lines)):
            next_level = heading_level(lines[cursor])
            if next_level is not None and next_level <= level:
                end = cursor
                break
        prefix = lines[:end]
        suffix = lines[end:]
        while prefix and prefix[-1].strip() == "":
            prefix.pop()
        merged = prefix + ["", content]
        if suffix:
            merged += ["", *suffix]
        return "\n".join(merged).rstrip() + "\n"

    addition = f"{heading_line}\n\n{content}"
    if not existing.strip():
        return addition + "\n"
    return existing.rstrip() + "\n\n" + addition + "\n"


__all__ = [
    "SECRET_PLACEHOLDER",
    "HeadingMatchError",
    "TaskMatchError",
    "append_under_heading",
    "bullet_list",
    "canonical_task_text",
    "excerpt_around",
    "extract_title",
    "find_canonical_task",
    "find_matching_task",
    "find_task_across_sources",
    "format_date",
    "format_frontmatter",
    "format_heading_time",
    "format_iso_datetime",
    "heading_level",
    "heading_title",
    "join_blocks",
    "local_now",
    "move_open_checkbox",
    "move_task_bullet",
    "normalize_heading",
    "normalize_task_text",
    "parse_bullets",
    "parse_frontmatter_fields",
    "parse_open_checkboxes",
    "parse_open_todo_entries",
    "parse_project_state",
    "patch_project_state_sections",
    "redact_secrets",
    "resolve_unique_task",
    "section",
    "set_frontmatter_field",
    "slugify",
    "strip_frontmatter",
]
