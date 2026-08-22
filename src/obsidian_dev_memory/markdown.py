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
        r"(?i)\b(?:password|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|"
        r"private[_-]?key|db[_-]?password|authorization)\s*[:=]\s*\S+"
    ),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-+=/]{16,}"),
)

_UNSAFE_SLUG_RE = re.compile(r"[^a-z0-9-]+")
_REPEAT_DASH_RE = re.compile(r"-{2,}")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(\S.*)$")


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


def append_under_heading(existing: str, content: str, heading: str | None = None) -> str:
    """Append content under a heading, creating the heading when missing."""
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

    for index, line in enumerate(lines):
        if heading_level(line) is None:
            continue
        if heading_title(line) != target:
            continue
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
    "append_under_heading",
    "bullet_list",
    "excerpt_around",
    "extract_title",
    "format_date",
    "format_frontmatter",
    "format_heading_time",
    "format_iso_datetime",
    "heading_level",
    "heading_title",
    "join_blocks",
    "local_now",
    "normalize_heading",
    "redact_secrets",
    "section",
    "slugify",
]
