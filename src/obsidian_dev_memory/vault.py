"""Safe CRUD operations against an Obsidian Markdown vault."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from obsidian_dev_memory.git_context import collect_git_context
from obsidian_dev_memory.markdown import (
    SECRET_PLACEHOLDER,
    HeadingMatchError,
    TaskMatchError,
    append_under_heading,
    bullet_list,
    excerpt_around,
    extract_title,
    find_matching_task,
    format_date,
    format_frontmatter,
    format_heading_time,
    format_iso_datetime,
    heading_level,
    heading_title,
    join_blocks,
    local_now,
    move_open_checkbox,
    move_task_bullet,
    normalize_task_text,
    parse_bullets,
    parse_frontmatter_fields,
    parse_open_checkboxes,
    parse_open_todo_entries,
    parse_project_state,
    patch_project_state_sections,
    redact_secrets,
    resolve_unique_task,
    section,
    set_frontmatter_field,
    slugify,
)
from obsidian_dev_memory.models import (
    GitInfo,
    MemoryDocument,
    OpenTask,
    OpenTaskList,
    ProjectContext,
    SearchHit,
    TaskMoveResult,
    WriteResult,
)

DEFAULT_MEMORY_ROOT = "AI Memory"
DEFAULT_AGENT_QUEUE = "Agent Queue.md"
DEFAULT_TODO_ROOT = "TODO"
DEFAULT_DAILY_ROOT = "Daily"
DEFAULT_CONTEXT_LIMIT = 4000
DEFAULT_SEARCH_LIMIT = 20
DEFAULT_EXCERPT_LIMIT = 240
_TODO_CLAIM_NOTE_STATUSES = frozenset({"open"})
_TODO_COMPLETE_NOTE_STATUSES = frozenset({"open", "in_progress", "claimed"})


class _TodoMatch(NamedTuple):
    text: str
    path: Path
    kind: str


class _QueueSync(NamedTuple):
    path: str
    body: str | None
    status: str


# Run before the labeled-assignment redactor, which keeps only the word Bearer.
_BEARER_VALUE_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-+=/]{16,}")


def _shield_bearer_value(text: str) -> str:
    """Replace a Bearer token so a later assignment pattern cannot leave it."""
    return _BEARER_VALUE_RE.sub(SECRET_PLACEHOLDER, text)


def _public_text(text: str) -> str:
    return redact_secrets(_shield_bearer_value(text))


def _read_utf8(path: Path) -> str:
    """Read a note as UTF-8, or refuse bytes that are not text."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise VaultError("Note is not valid UTF-8") from exc


def _shield_text(text: str | None) -> str | None:
    if text is None:
        return None
    return _shield_bearer_value(text)


def _shield_sequence(items: Sequence[str] | None) -> Sequence[str] | None:
    if not items:
        return items
    return [_shield_bearer_value(str(item)) for item in items]


def _shield_extras(
    sections: Sequence[tuple[str, str]] | None,
) -> Sequence[tuple[str, str]] | None:
    if not sections:
        return sections
    return [(title, _shield_bearer_value(str(body))) for title, body in sections]


def _reject_level2_heading(text: str) -> None:
    """Refuse field text that would be parsed as a new project-state section."""
    for line in text.splitlines():
        if heading_level(line) == 2:
            raise VaultError("Project state fields cannot contain a Markdown heading")


def _state_text(text: str | None) -> str | None:
    if text is None:
        return None
    value = _shield_bearer_value(text)
    _reject_level2_heading(value)
    return value


def _reject_extra_task_line(text: str) -> None:
    """Refuse one list item that would parse as more than one task."""
    if len(parse_bullets(bullet_list([text]))) > 1:
        raise VaultError("Project state fields cannot contain an extra task")


def _state_list_item(text: str) -> str:
    value = _state_text(text) or ""
    _reject_extra_task_line(value)
    return value


def _state_sequence(items: Sequence[str] | None) -> Sequence[str] | None:
    if not items:
        return items
    return [_state_list_item(str(item)) for item in items]


def _state_extras(
    sections: Sequence[tuple[str, str]] | None,
) -> Sequence[tuple[str, str]] | None:
    if not sections:
        return sections
    rendered: list[tuple[str, str]] = []
    for title, body in sections:
        rendered.append((_state_text(str(title)) or "", _state_text(str(body)) or ""))
    return rendered


def _kept_blocked(
    existing: str,
    blocked: Sequence[str] | None,
) -> Sequence[str] | None:
    """Keep Blockers bullets when a patch omits the Blocked field."""
    if blocked is not None:
        return blocked
    titles = [
        heading_title(line)
        for line in existing.splitlines()
        if heading_level(line) == 2
    ]
    if "blocked" not in titles or "blockers" not in titles:
        return None
    parsed = parse_project_state(existing)["blocked"]
    if not isinstance(parsed, list) or not parsed:
        return None
    return [str(item) for item in parsed]


def _frontmatter_has_project_key(note: str | None) -> bool:
    """True when frontmatter names project, even if the value is not a scalar."""
    if not note:
        return False
    lines = note.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    for line in lines[1:]:
        if line.strip() == "---":
            return False
        key, separator, _value = line.partition(":")
        if separator and key.strip().lower() == "project":
            return True
    return False


def _is_frontmatter_status(line: str) -> bool:
    """True for a top-level frontmatter status key."""
    if not line or line[0] in {" ", "\t", "-"}:
        return False
    key, separator, _value = line.partition(":")
    return bool(separator) and key.strip().lower() == "status"


def _frontmatter_lines(note: str) -> list[str] | None:
    """Return the opening frontmatter lines, including the closing marker."""
    lines = note.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    collected = [lines[0]]
    for line in lines[1:]:
        collected.append(line)
        if line.strip() == "---":
            return collected
    return None


def _replace_status_lines(lines: list[str], rendered: str) -> list[str] | None:
    """Replace each frontmatter status line. Return None when nothing changes."""
    changed = False
    updated: list[str] = []
    for line in lines:
        if _is_frontmatter_status(line) and line != rendered:
            updated.append(rendered)
            changed = True
            continue
        updated.append(line)
    if not changed:
        return None
    return updated


def _with_frontmatter_lines(note: str, front_lines: list[str]) -> str:
    rest = note.splitlines()[len(front_lines) :]
    text = "\n".join([*front_lines, *rest])
    if note.endswith("\n"):
        text += "\n"
    return text


def _clear_duplicate_status(note: str, status: str) -> str:
    """Set every frontmatter status so a later field cannot stay open."""
    front = _frontmatter_lines(note)
    if front is None:
        return note
    replaced = _replace_status_lines(front, f"status: {status}")
    if replaced is None:
        return note
    return _with_frontmatter_lines(note, replaced)


def _set_note_status(note: str, status: str) -> str:
    """Update a TODO status, including a duplicate later status field."""
    return _clear_duplicate_status(set_frontmatter_field(note, "status", status), status)


_CHECKED_NEXT_STEP_RE = re.compile(r"^[-*+]\s+\[[xX]\]\s+(.*\S)\s*$")


def _checked_next_step_keys(note: str) -> set[str]:
    """Return normalized texts of checked boxes under Next Steps."""
    keys: set[str] = set()
    in_section = False
    for line in note.splitlines():
        if heading_level(line) == 2:
            in_section = heading_title(line) == "next steps"
            continue
        if not in_section:
            continue
        match = _CHECKED_NEXT_STEP_RE.match(line)
        if match is None:
            continue
        keys.add(normalize_task_text(match.group(1)))
    return keys


def _drop_checked_next_steps(items: Sequence[str], note: str) -> list[str]:
    """Drop Next Steps items that are already checked off."""
    checked = _checked_next_step_keys(note)
    texts = [str(item) for item in items]
    if not checked:
        return texts
    return [item for item in texts if normalize_task_text(item) not in checked]


def _fence_marker(line: str) -> bool:
    """True for a line that opens or closes a fenced code block."""
    stripped = line.strip()
    return stripped.startswith("```") or stripped.startswith("~~~")


_INDENTED_HEADING_RE = re.compile(r"^[ ]{1,3}(#{1,6}[ \t]+\S.*)$")


def _open_headings(text: str) -> str:
    """Recognize a heading indented by up to three spaces, outside a fence."""
    lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _fence_marker(line):
            in_fence = not in_fence
        elif not in_fence:
            line = _INDENTED_HEADING_RE.sub(r"\1", line, count=1)
        lines.append(line)
    return "\n".join(lines)


def _fenced_next_step_keys(note: str) -> set[str]:
    """Return normalized texts of bullets that sit inside a Next Steps fence."""
    keys: set[str] = set()
    in_fence = False
    in_next = False
    for line in note.splitlines():
        if _fence_marker(line):
            in_fence = not in_fence
            continue
        if heading_level(line) == 2:
            in_next = heading_title(line) == "next steps"
            continue
        if not in_fence or not in_next:
            continue
        for item in parse_bullets(line):
            keys.add(normalize_task_text(item))
    return keys


def _drop_fenced_next_steps(items: Sequence[str], note: str) -> list[str]:
    """Drop Next Steps items that only appear inside a code fence."""
    fenced = _fenced_next_step_keys(note)
    texts = [str(item) for item in items]
    if not fenced:
        return texts
    return [item for item in texts if normalize_task_text(item) not in fenced]


_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _without_html_comments(text: str) -> str:
    """Drop HTML comments so an example heading is not the open task."""
    return _HTML_COMMENT_RE.sub("", text)


def _without_matched_task(items: Sequence[str], task: str) -> list[str]:
    """Drop open copies of a task that has been completed."""
    needle = normalize_task_text(task)
    return [item for item in items if normalize_task_text(item) != needle]


class VaultError(Exception):
    """Base error for vault operations.

    Messages are tool-facing, so secret-looking text is redacted here.
    On-disk notes are left unchanged.
    """

    def __init__(self, message: object = "", *args: object) -> None:
        parts = (message, *args)
        redacted = tuple(
            _public_text(part) if isinstance(part, str) else part for part in parts
        )
        super().__init__(*redacted)


class VaultConfigError(VaultError):
    """Missing or invalid vault configuration."""


class VaultPathError(VaultError):
    """Rejected path that is outside the vault or otherwise unsafe."""


class Vault:
    """Filesystem-backed engineering memory constrained to one vault."""

    def __init__(self, root: str | Path, memory_root: str = DEFAULT_MEMORY_ROOT) -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.exists() or not self.root.is_dir():
            raise VaultConfigError(f"Obsidian vault does not exist: {self.root}")
        memory_root = memory_root.strip() or DEFAULT_MEMORY_ROOT
        if Path(memory_root).is_absolute() or ".." in Path(memory_root).parts:
            raise VaultConfigError("OBSIDIAN_MEMORY_ROOT must be a relative vault folder")
        self.memory_root = memory_root

    @classmethod
    def from_env(cls) -> Vault:
        raw = os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
        if not raw:
            raise VaultConfigError("OBSIDIAN_VAULT_PATH is required")
        memory_root = os.environ.get("OBSIDIAN_MEMORY_ROOT", DEFAULT_MEMORY_ROOT)
        return cls(raw, memory_root=memory_root)

    def project_slug(self, project: str) -> str:
        return slugify(project)

    def relative_path(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def safe_path(self, *parts: str) -> Path:
        """Resolve a vault-relative path and reject traversal or symlink escapes."""
        raw = self._relative_note_path(parts)
        current = self._walk_contained_parts(raw)
        return self._finish_contained_path(current)

    def _relative_note_path(self, parts: tuple[str, ...]) -> Path:
        if not parts:
            raise VaultPathError("A vault-relative path is required")
        raw = Path(*[str(part) for part in parts])
        self._reject_unsafe_relative_path(raw)
        return raw

    def _reject_unsafe_relative_path(self, raw: Path) -> None:
        if raw.is_absolute() or raw.as_posix().startswith("~"):
            raise VaultPathError("Absolute paths are not allowed as note paths")
        if self._has_traversal_part(raw):
            raise VaultPathError("Path traversal is not allowed")
        if "\x00" in raw.as_posix():
            raise VaultPathError("Invalid path")

    def _has_traversal_part(self, raw: Path) -> bool:
        return any(part in {"..", ""} or part.startswith("..") for part in raw.parts)

    def _walk_contained_parts(self, raw: Path) -> Path:
        current = self.root
        for part in raw.parts:
            current = current / part
            self._reject_resolved_escape(current)
        return current

    def _reject_resolved_escape(self, current: Path) -> None:
        self._reject_in_vault_markdown_symlink(current)
        if not (current.exists() or current.is_symlink()):
            return
        resolved = current.resolve()
        if not self._contained(resolved):
            raise VaultPathError("Resolved path escapes the vault")

    def _reject_in_vault_markdown_symlink(self, current: Path) -> None:
        """Refuse a symlink whose target is a Markdown note inside the vault."""
        if not current.is_symlink():
            return
        resolved = current.resolve()
        if self._contained(resolved) and resolved.suffix.lower() == ".md":
            raise VaultPathError("Symlinks are not allowed as note paths")

    def _finish_contained_path(self, current: Path) -> Path:
        if current.exists() or current.is_symlink():
            resolved = current.resolve()
            if not self._contained(resolved):
                raise VaultPathError("Resolved path escapes the vault")
            return resolved
        parent = current.parent.resolve()
        if not self._contained(parent):
            raise VaultPathError("Resolved path escapes the vault")
        return parent / current.name

    def ensure_project(self, project: str) -> Path:
        slug = self.project_slug(project)
        project_dir = self.safe_path(self.memory_root, "Projects", slug)
        sessions = self.safe_path(self.memory_root, "Projects", slug, "Sessions")
        decisions = self.safe_path(self.memory_root, "Projects", slug, "Decisions")
        project_dir.mkdir(parents=True, exist_ok=True)
        sessions.mkdir(parents=True, exist_ok=True)
        decisions.mkdir(parents=True, exist_ok=True)
        self._assert_inside(project_dir)
        return project_dir

    def project_state_path(self, project: str) -> Path:
        slug = self.project_slug(project)
        return self.safe_path(self.memory_root, "Projects", slug, "Project State.md")

    def get_project_context(
        self,
        project: str,
        recent_sessions: int = 5,
        recent_decisions: int = 10,
    ) -> ProjectContext:
        slug = self.project_slug(project)
        state_path = self.project_state_path(project)
        project_state = ""
        if state_path.exists() and state_path.is_file():
            project_state = self._read_text(state_path)

        return ProjectContext(
            project=slug,
            project_state=self._compact(project_state),
            recent_sessions=self._recent_markdown(
                self.safe_path(self.memory_root, "Projects", slug, "Sessions"),
                limit=max(0, recent_sessions),
            ),
            recent_decisions=self._recent_markdown(
                self.safe_path(self.memory_root, "Projects", slug, "Decisions"),
                limit=max(0, recent_decisions),
            ),
        )

    def capture_work_session(
        self,
        project: str,
        summary: str,
        changes: Sequence[str] | None = None,
        decisions: Sequence[str] | None = None,
        open_questions: Sequence[str] | None = None,
        next_steps: Sequence[str] | None = None,
        repository_path: str | None = None,
        now: datetime | None = None,
    ) -> WriteResult:
        self.ensure_project(project)
        stamp = local_now(now)
        slug = self.project_slug(project)
        session_path = self.safe_path(
            self.memory_root,
            "Projects",
            slug,
            "Sessions",
            f"{format_date(stamp)}.md",
        )
        git_info = collect_git_context(repository_path)
        entry = self._render_session_entry(
            summary=summary,
            changes=changes,
            decisions=decisions,
            open_questions=open_questions,
            next_steps=next_steps,
            git_info=git_info,
            now=stamp,
        )
        return self._append_session_entry(session_path, slug, stamp, entry)

    def _append_session_entry(
        self,
        session_path: Path,
        project_slug: str,
        stamp: datetime,
        entry: str,
    ) -> WriteResult:
        """Append one session entry without losing a concurrent append."""
        with self._exclusive_session_lock(project_slug, format_date(stamp)):
            existing = self._read_text(session_path) if session_path.exists() else ""
            created = not session_path.exists()
            self._atomic_write(session_path, join_blocks(existing, entry))
            return WriteResult(
                path=self.relative_path(session_path),
                created=created,
                message="Appended work session",
            )

    def record_decision(
        self,
        project: str,
        title: str,
        context: str,
        decision: str,
        rationale: str = "",
        consequences: Sequence[str] | None = None,
        alternatives: Sequence[str] | None = None,
        related_files: Sequence[str] | None = None,
        now: datetime | None = None,
    ) -> WriteResult:
        self.ensure_project(project)
        stamp = local_now(now)
        slug = self.project_slug(project)
        path, suffix_used = self._unique_decision_path(slug, title, stamp)
        body = join_blocks(
            format_frontmatter(
                {
                    "type": "decision",
                    "project": slug,
                    "date": format_date(stamp),
                    "status": "accepted",
                    "tags": ["architecture", "decision"],
                }
            ),
            f"# {_public_text(title.strip())}",
            section("Context", _shield_bearer_value(context)),
            section("Decision", _shield_bearer_value(decision)),
            section("Rationale", _shield_bearer_value(rationale)),
            section("Consequences", _shield_sequence(consequences)),
            section("Alternatives Considered", _shield_sequence(alternatives)),
            section("Related Files", _shield_sequence(related_files)),
        )
        self._atomic_write(path, body)
        message = "Recorded decision"
        if suffix_used:
            message = (
                "Recorded decision with numeric suffix because the generated "
                "filename already existed"
            )
        return WriteResult(path=self.relative_path(path), created=True, message=message)

    def update_project_state(
        self,
        project: str,
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
        now: datetime | None = None,
    ) -> WriteResult:
        self.ensure_project(project)
        stamp = local_now(now)
        slug = self.project_slug(project)
        path = self.project_state_path(project)
        created = not path.exists()
        existing = self._read_text(path) if not created else ""
        body = join_blocks(
            format_frontmatter(
                {
                    "type": "project-state",
                    "project": slug,
                    "updated": format_iso_datetime(stamp),
                }
            ),
            "# Project State",
            *patch_project_state_sections(
                existing,
                objective=_state_text(objective),
                current_state=_state_text(current_state),
                architecture=_state_sequence(architecture),
                completed=_state_sequence(completed),
                in_progress=_state_sequence(in_progress),
                blocked=_shield_sequence(_kept_blocked(existing, _state_sequence(blocked))),
                next_steps=_state_sequence(next_steps),
                important_files=_state_sequence(important_files),
                notes=_state_sequence(notes),
                extra_sections=_state_extras(extra_sections),
            ),
        )
        self._atomic_write(path, body)
        return WriteResult(
            path=self.relative_path(path),
            created=created,
            message="Updated project state",
        )

    def agent_queue_path(self) -> Path:
        return self.safe_path(self.memory_root, DEFAULT_AGENT_QUEUE)

    def list_open_tasks(
        self,
        project: str,
        include_agent_queue: bool = True,
    ) -> OpenTaskList:
        slug = self.project_slug(project)
        tasks: list[OpenTask] = []
        seen: set[str] = set()
        self._append_next_step_tasks(project, tasks, seen)
        if include_agent_queue:
            self._append_agent_queue_tasks(tasks, seen)
        self._append_todo_open_tasks(slug, tasks, seen)
        return OpenTaskList(project=slug, tasks=tasks)

    def _append_next_step_tasks(
        self,
        project: str,
        tasks: list[OpenTask],
        seen: set[str],
    ) -> None:
        state_path = self.project_state_path(project)
        if not (state_path.exists() and state_path.is_file()):
            return
        parsed = self._load_project_state(project)
        rel = self.relative_path(state_path)
        for item in parsed["next_steps"]:
            text = _public_text(str(item))
            self._append_open_task(tasks, seen, text, "next_steps", rel)

    def _append_agent_queue_tasks(self, tasks: list[OpenTask], seen: set[str]) -> None:
        queue_path = self.agent_queue_path()
        if not (queue_path.exists() and queue_path.is_file()):
            return
        rel = self.relative_path(queue_path)
        for item in parse_open_checkboxes(self._read_text(queue_path)):
            text = _public_text(item)
            self._append_open_task(tasks, seen, text, "agent_queue", rel)

    def _append_todo_open_tasks(
        self,
        slug: str,
        tasks: list[OpenTask],
        seen: set[str],
    ) -> None:
        for match in self._collect_todo_items(slug, note_statuses=_TODO_CLAIM_NOTE_STATUSES):
            text = _public_text(match.text)
            source = "todo" if match.kind == "note" else "todo_item"
            self._append_open_task(
                tasks,
                seen,
                text,
                source,
                self.relative_path(match.path),
            )

    def _append_open_task(
        self,
        tasks: list[OpenTask],
        seen: set[str],
        text: str,
        source: str,
        path: str,
    ) -> None:
        key = normalize_task_text(text)
        if not key or key in seen:
            return
        seen.add(key)
        tasks.append(OpenTask(text=text, source=source, path=path))

    def list_blocked_tasks(self, project: str) -> OpenTaskList:
        slug = self.project_slug(project)
        tasks: list[OpenTask] = []
        seen: set[str] = set()

        state_path = self.project_state_path(project)
        if state_path.exists() and state_path.is_file():
            parsed = parse_project_state(self._read_text(state_path))
            rel = self.relative_path(state_path)
            for item in parsed["blocked"]:
                text = _public_text(str(item))
                key = normalize_task_text(text)
                if not key or key in seen:
                    continue
                seen.add(key)
                tasks.append(OpenTask(text=text, source="blocked", path=rel))

        return OpenTaskList(project=slug, tasks=tasks)

    def claim_task(
        self,
        project: str,
        task: str,
        now: datetime | None = None,
    ) -> TaskMoveResult:
        with self._exclusive_task_lock(project):
            parsed = self._load_project_state(project)
            in_progress = [str(item) for item in parsed["in_progress"]]
            next_steps = [str(item) for item in parsed["next_steps"]]
            matched, from_section = self._resolve_task_match(
                task,
                (
                    ("In Progress", in_progress),
                    ("Next Steps", next_steps),
                    ("Agent Queue", self._open_queue_items()),
                    (
                        "TODO",
                        self._todo_texts(project, note_statuses=_TODO_CLAIM_NOTE_STATUSES),
                    ),
                ),
                prefer=("In Progress", "Next Steps", "Agent Queue", "TODO"),
            )
            if from_section == "In Progress":
                raise VaultError(f"Task already in progress: {matched}")
            if from_section == "Next Steps":
                next_steps, in_progress, matched = move_task_bullet(
                    next_steps,
                    in_progress,
                    matched,
                )
            else:
                in_progress = self._append_unique_task(in_progress, matched)
            parsed["next_steps"] = next_steps
            parsed["in_progress"] = in_progress
            return self._rewrite_moved_task(
                project=project,
                parsed=parsed,
                matched=matched,
                from_section=from_section,
                to_section="In Progress",
                message="Claimed task",
                now=now,
                task_query=matched,
                todo_status="in_progress",
            )

    def complete_task(
        self,
        project: str,
        task: str,
        now: datetime | None = None,
    ) -> TaskMoveResult:
        with self._exclusive_task_lock(project):
            parsed = self._load_project_state(project)
            in_progress = [str(item) for item in parsed["in_progress"]]
            completed = [str(item) for item in parsed["completed"]]
            next_steps = [str(item) for item in parsed["next_steps"]]
            matched, from_section = self._resolve_task_match(
                task,
                (
                    ("In Progress", in_progress),
                    ("Next Steps", next_steps),
                    ("Agent Queue", self._open_queue_items()),
                    (
                        "TODO",
                        self._todo_texts(
                            project, note_statuses=_TODO_COMPLETE_NOTE_STATUSES
                        ),
                    ),
                ),
                prefer=("In Progress", "Agent Queue", "TODO"),
            )
            if from_section == "In Progress":
                in_progress, completed, matched = move_task_bullet(
                    in_progress,
                    completed,
                    matched,
                )
            else:
                completed = self._append_unique_task(completed, matched)
            parsed["in_progress"] = in_progress
            parsed["completed"] = completed
            parsed["next_steps"] = _without_matched_task(next_steps, matched)
            return self._rewrite_moved_task(
                project=project,
                parsed=parsed,
                matched=matched,
                from_section=from_section,
                to_section="Completed",
                message="Completed task",
                now=now,
                task_query=matched,
                todo_status="done",
            )

    def block_task(
        self,
        project: str,
        task: str,
        now: datetime | None = None,
    ) -> TaskMoveResult:
        with self._exclusive_task_lock(project):
            parsed = self._load_project_state(project)
            next_steps = [str(item) for item in parsed["next_steps"]]
            in_progress = [str(item) for item in parsed["in_progress"]]
            blocked = [str(item) for item in parsed["blocked"]]
            already = self._exact_task_match(blocked, task)
            if already is not None:
                raise VaultError(f"Task already blocked: {already}")
            matched, from_section = self._resolve_task_match(
                task,
                (
                    ("Blocked", blocked),
                    ("Next Steps", next_steps),
                    ("In Progress", in_progress),
                    ("Agent Queue", self._open_queue_items()),
                    (
                        "TODO",
                        self._todo_texts(project, note_statuses=_TODO_CLAIM_NOTE_STATUSES),
                    ),
                ),
                prefer=("Blocked", "Next Steps", "In Progress"),
            )
            if from_section == "Blocked":
                raise VaultError(f"Task already blocked: {matched}")
            if from_section == "Next Steps":
                next_steps, blocked, matched = move_task_bullet(
                    next_steps, blocked, matched
                )
            else:
                in_progress, blocked, matched = move_task_bullet(
                    in_progress, blocked, matched
                )
            parsed["next_steps"] = next_steps
            parsed["in_progress"] = in_progress
            parsed["blocked"] = blocked
            return self._rewrite_moved_task(
                project=project,
                parsed=parsed,
                matched=matched,
                from_section=from_section,
                to_section="Blocked",
                message="Blocked task",
                now=now,
                task_query=matched,
                sync_agent_queue=False,
            )

    def unblock_task(
        self,
        project: str,
        task: str,
        now: datetime | None = None,
    ) -> TaskMoveResult:
        with self._exclusive_task_lock(project):
            parsed = self._load_project_state(project)
            next_steps = [str(item) for item in parsed["next_steps"]]
            blocked = [str(item) for item in parsed["blocked"]]
            already = self._exact_task_match(next_steps, task)
            if already is not None:
                raise VaultError(f"Task already in next steps: {already}")
            matched, from_section = self._resolve_task_match(
                task,
                (
                    ("Next Steps", next_steps),
                    ("Blocked", blocked),
                    ("Agent Queue", self._open_queue_items()),
                    (
                        "TODO",
                        self._todo_texts(project, note_statuses=_TODO_CLAIM_NOTE_STATUSES),
                    ),
                ),
                prefer=("Next Steps", "Blocked"),
            )
            if from_section == "Next Steps":
                raise VaultError(f"Task already in next steps: {matched}")
            blocked, next_steps, matched = move_task_bullet(
                blocked, next_steps, matched
            )
            parsed["blocked"] = blocked
            parsed["next_steps"] = next_steps
            return self._rewrite_moved_task(
                project=project,
                parsed=parsed,
                matched=matched,
                from_section="Blocked",
                to_section="Next Steps",
                message="Unblocked task",
                now=now,
                task_query=matched,
                sync_agent_queue=False,
            )

    def _load_project_state(
        self, project: str
    ) -> dict[str, str | list[str] | list[tuple[str, str]]]:
        path = self.project_state_path(project)
        if not path.exists() or not path.is_file():
            return parse_project_state("")
        raw = self._read_text(path)
        parsed = parse_project_state(_open_headings(raw))
        parsed["next_steps"] = _drop_fenced_next_steps(
            _drop_checked_next_steps(parsed["next_steps"], raw),
            raw,
        )
        return parsed

    def _exact_task_match(self, items: Sequence[str], query: str) -> str | None:
        needle = normalize_task_text(query)
        if not needle:
            raise VaultError("task text is required")
        exact = [item for item in items if normalize_task_text(item) == needle]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise VaultError(f"Ambiguous task match for {query!r}")
        return None

    def _append_unique_task(self, items: Sequence[str], task: str) -> list[str]:
        updated = list(items)
        if not any(normalize_task_text(item) == normalize_task_text(task) for item in updated):
            updated.append(task)
        return updated

    def _open_queue_items(self) -> list[str]:
        path = self.agent_queue_path()
        if not path.exists() or not path.is_file():
            return []
        return parse_open_checkboxes(self._read_text(path))

    def _todo_texts(
        self,
        project: str,
        *,
        note_statuses: frozenset[str],
    ) -> list[str]:
        return [
            item.text
            for item in self._collect_todo_items(project, note_statuses=note_statuses)
        ]

    def _resolve_task_match(
        self,
        task: str,
        sources: Sequence[tuple[str, Sequence[str]]],
        *,
        prefer: Sequence[str],
    ) -> tuple[str, str]:
        try:
            return resolve_unique_task(sources, task, prefer=prefer)
        except TaskMatchError as exc:
            raise VaultError(str(exc)) from exc

    @contextmanager
    def _exclusive_task_lock(self, project: str) -> Iterator[None]:
        """Serialize claim/complete/block/unblock for one project.

        The lock file lives in the process temp dir so the vault is never
        given an extra note (including Agent Queue.md).
        """
        slug = self.project_slug(project)
        key = hashlib.sha256(f"{self.root}:{slug}".encode()).hexdigest()[:16]
        lock_path = Path(tempfile.gettempdir()) / f"obsidian-mcp-task-{key}.lock"
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _exclusive_session_lock(self, project_slug: str, day: str) -> Iterator[None]:
        """Serialize session appends for one project day.

        The lock file lives in the process temp dir so the vault is never
        given an extra note (including Agent Queue.md).
        """
        key = hashlib.sha256(
            f"{self.root}:session:{project_slug}:{day}".encode()
        ).hexdigest()[:16]
        lock_path = Path(tempfile.gettempdir()) / f"obsidian-mcp-session-{key}.lock"
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _exclusive_daily_lock(self, day: str) -> Iterator[None]:
        """Serialize append_daily_note for one calendar day.

        The lock file lives in the process temp dir so the vault is never
        given an extra note (including Agent Queue.md).
        """
        key = hashlib.sha256(f"{self.root}:daily:{day}".encode()).hexdigest()[:16]
        lock_path = Path(tempfile.gettempdir()) / f"obsidian-mcp-daily-{key}.lock"
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _prepare_queue_check(self, task: str, *, required: bool = False) -> _QueueSync:
        """Prepare a unique Agent Queue checkbox check, or fail closed.

        Missing ``Agent Queue.md`` is reported, never invented. Ambiguous
        matches raise so Project State is not written while boxes stay open.
        """
        path = self.agent_queue_path()
        if not path.exists() or not path.is_file():
            if required:
                raise VaultError("Agent Queue is missing; task left unchecked")
            return _QueueSync("", None, "missing")
        existing = self._read_text(path)
        rel = self.relative_path(path)
        try:
            updated, _matched = move_open_checkbox(existing, task, canonical=True)
        except TaskMatchError as exc:
            detail = str(exc)
            if "Ambiguous" in detail or required:
                raise VaultError(detail) from exc
            return _QueueSync(rel, None, "unchecked")
        if updated == existing:
            if required:
                raise VaultError(f"Agent Queue item left unchecked for {task!r}")
            return _QueueSync(rel, None, "unchecked")
        return _QueueSync(rel, updated, "updated")

    def _commit_queue_then_state(
        self,
        queue_sync: _QueueSync,
        *,
        project: str,
        parsed: dict[str, str | list[str] | list[tuple[str, str]]],
        now: datetime | None,
    ) -> WriteResult:
        """Check the queue, then write state. Reopen the box if state fails."""
        previous = self._store_queue_body(queue_sync)
        try:
            return self.update_project_state(project=project, now=now, **parsed)
        except Exception:
            self._restore_queue_body(previous)
            raise

    def _store_queue_body(self, queue_sync: _QueueSync) -> str | None:
        if queue_sync.body is None:
            return None
        path = self.agent_queue_path()
        previous = self._read_text(path)
        self._atomic_write(path, queue_sync.body)
        return previous

    def _restore_queue_body(self, previous: str | None) -> None:
        if previous is None:
            return
        self._atomic_write(self.agent_queue_path(), previous)

    def _queue_sync_message(self, message: str, status: str) -> str:
        if status == "updated":
            return f"{message} and checked Agent Queue item"
        if status == "missing":
            return f"{message}; Agent Queue missing (left unchecked)"
        if status == "unchecked":
            return f"{message}; Agent Queue left unchecked"
        return message

    def _rewrite_moved_task(
        self,
        *,
        project: str,
        parsed: dict[str, str | list[str] | list[tuple[str, str]]],
        matched: str,
        from_section: str,
        to_section: str,
        message: str,
        now: datetime | None,
        task_query: str,
        sync_agent_queue: bool = True,
        todo_status: str | None = None,
    ) -> TaskMoveResult:
        queue_sync = _QueueSync("", None, "skipped")
        if sync_agent_queue:
            queue_sync = self._prepare_queue_check(
                task_query,
                required=from_section == "Agent Queue",
            )
        todo_path, todo_body = ("", None)
        if todo_status:
            todo_path, todo_body = self._prepare_todo_update(
                project,
                matched,
                status=todo_status,
            )
        # Write the queue before Project State so a later state write cannot
        # report success while a matching box stays open. Put the box back
        # if that state write fails.
        written = self._commit_queue_then_state(
            queue_sync,
            project=project,
            parsed=parsed,
            now=now,
        )
        todo_updated = False
        if todo_body is not None:
            self._atomic_write(self.safe_path(todo_path), todo_body)
            todo_updated = True
        queue_updated = queue_sync.status == "updated"
        message = self._queue_sync_message(message, queue_sync.status)
        if todo_updated:
            message = f"{message} and updated TODO note"
        return TaskMoveResult(
            path=written.path,
            created=written.created,
            message=message,
            task=_public_text(matched),
            from_section=from_section,
            to_section=to_section,
            queue_updated=queue_updated,
            queue_path=queue_sync.path if queue_updated else "",
            queue_status=queue_sync.status,
            todo_updated=todo_updated,
            todo_path=todo_path if todo_updated else "",
        )

    def _iter_todo_notes(self) -> list[Path]:
        """Return top-level ``TODO/*.md`` notes. Does not create the folder."""
        return self._iter_top_level_markdown(DEFAULT_TODO_ROOT)

    def _iter_daily_notes(self) -> list[Path]:
        """Return top-level ``Daily/*.md`` notes. Does not create the folder."""
        return self._iter_top_level_markdown(DEFAULT_DAILY_ROOT)

    def _iter_top_level_markdown(self, folder: str) -> list[Path]:
        """Return ``folder/*.md`` notes. Does not create the folder."""
        try:
            directory = self.safe_path(folder)
        except VaultPathError:
            return []
        if not directory.exists() or not directory.is_dir():
            return []
        files: list[Path] = []
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            if not path.is_file() or path.suffix.lower() != ".md":
                continue
            try:
                resolved = self.safe_path(folder, path.name)
            except VaultPathError:
                continue
            if resolved.is_file() and self._contained(resolved.resolve()):
                files.append(resolved)
        return files

    def _todo_belongs_to_project(
        self,
        fields: dict[str, str],
        project_slug: str,
        note: str | None = None,
    ) -> bool:
        raw = fields.get("project", "").strip()
        if not raw:
            return not _frontmatter_has_project_key(note)
        try:
            return slugify(raw) == project_slug
        except ValueError:
            return False

    def _collect_todo_items(
        self,
        project: str,
        *,
        note_statuses: frozenset[str],
    ) -> list[_TodoMatch]:
        slug = self.project_slug(project)
        items: list[_TodoMatch] = []
        for path in self._iter_todo_notes():
            text = self._read_text(path)
            fields = parse_frontmatter_fields(text)
            if not self._todo_belongs_to_project(fields, slug, text):
                continue
            for entry_text, kind in parse_open_todo_entries(
                _without_html_comments(text),
                path.stem,
                note_statuses=note_statuses,
            ):
                items.append(_TodoMatch(text=entry_text, path=path, kind=kind))
        return items

    def _find_todo_match(
        self,
        project: str,
        task: str,
        *,
        note_statuses: frozenset[str],
    ) -> _TodoMatch | None:
        items = self._collect_todo_items(project, note_statuses=note_statuses)
        if not items:
            return None
        try:
            matched = find_matching_task([item.text for item in items], task)
        except TaskMatchError as exc:
            if "No matching" in str(exc):
                return None
            raise VaultError(str(exc)) from exc
        hits = [
            item
            for item in items
            if normalize_task_text(item.text) == normalize_task_text(matched)
        ]
        if len(hits) != 1:
            raise VaultError(f"Ambiguous task match for {task!r}")
        return hits[0]

    def _prepare_todo_update(
        self,
        project: str,
        task: str,
        *,
        status: str,
    ) -> tuple[str, str | None]:
        """Return ``(todo_path, updated_body_or_none)`` for a unique open match."""
        note_statuses = (
            _TODO_COMPLETE_NOTE_STATUSES if status == "done" else _TODO_CLAIM_NOTE_STATUSES
        )
        match = self._find_todo_match(project, task, note_statuses=note_statuses)
        if match is None:
            return "", None
        existing = self._read_text(match.path)
        if match.kind == "checkbox":
            try:
                updated, _matched = move_open_checkbox(existing, match.text)
            except TaskMatchError:
                return "", None
        else:
            updated = _set_note_status(existing, status)
        if updated == existing:
            return "", None
        return self.relative_path(match.path), updated

    def search_memory(
        self,
        query: str,
        project: str | None = None,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[SearchHit]:
        """Search project notes and top-level TODO notes.

        Daily notes are included only when no project filter is set.
        """
        terms = [term.lower() for term in re.findall(r"[A-Za-z0-9_-]+", query)]
        if not terms:
            return []
        limit = max(1, limit)
        hits: list[SearchHit] = []
        for path in self._iter_memory_files(project):
            text = self._indexable_text(path)
            lowered = text.lower()
            filename = path.name.lower()
            score = 0.0
            for term in terms:
                if term in filename:
                    score += 8.0
                score += float(lowered.count(term))
            if score <= 0:
                continue
            rel = self.relative_path(path)
            hits.append(
                SearchHit(
                    path=rel,
                    title=_public_text(extract_title(text, path.stem)),
                    matching_excerpt=_public_text(
                        excerpt_around(text, terms, limit=DEFAULT_EXCERPT_LIMIT)
                    ),
                    score=score,
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.path))
        return hits[:limit]

    def read_note(self, path: str) -> dict[str, str]:
        target = self._markdown_note(path)
        return {
            "path": self.relative_path(target),
            "content": _public_text(self._read_text(target)),
        }

    def _markdown_note(self, path: str) -> Path:
        """Resolve one existing Markdown note, or fail closed."""
        target = self.safe_path(path)
        if not target.exists() or not target.is_file():
            raise VaultPathError(f"Note does not exist: {path}")
        self._require_markdown_note(target)
        return target

    def _require_markdown_note(self, path: Path) -> None:
        """Reject a resolved file that is not a Markdown note."""
        resolved = path.resolve() if path.exists() or path.is_symlink() else path
        if resolved.suffix.lower() != ".md":
            raise VaultPathError("Only Markdown notes can be read")

    def append_daily_note(
        self,
        content: str,
        heading: str | None = None,
        date: str | None = None,
        now: datetime | None = None,
    ) -> WriteResult:
        stamp = local_now(now)
        day = date.strip() if date and date.strip() else format_date(stamp)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise VaultError("date must be YYYY-MM-DD")
        path = self.safe_path(DEFAULT_DAILY_ROOT, f"{day}.md")
        with self._exclusive_daily_lock(day):
            existing = self._read_text(path) if path.exists() else ""
            created = not path.exists()
            try:
                updated = append_under_heading(
                    existing,
                    _shield_bearer_value(content),
                    heading,
                )
            except HeadingMatchError as exc:
                raise VaultError(str(exc)) from exc
            self._atomic_write(path, updated)
            return WriteResult(
                path=self.relative_path(path),
                created=created,
                message="Appended daily note",
            )

    def _unique_decision_path(
        self, project_slug: str, title: str, stamp: datetime
    ) -> tuple[Path, bool]:
        date = format_date(stamp)
        decision_slug = slugify(title)
        filename = f"{date}-{decision_slug}.md"
        path = self.safe_path(self.memory_root, "Projects", project_slug, "Decisions", filename)
        if not path.exists():
            return path, False
        for index in range(2, 1001):
            filename = f"{date}-{decision_slug}-{index}.md"
            candidate = self.safe_path(
                self.memory_root, "Projects", project_slug, "Decisions", filename
            )
            if not candidate.exists():
                return candidate, True
        raise VaultError("Too many decision filename collisions")

    def _recent_markdown(self, directory: Path, *, limit: int) -> list[MemoryDocument]:
        if limit <= 0 or not directory.exists() or not directory.is_dir():
            return []
        files = [
            path
            for path in directory.iterdir()
            if self._can_index_markdown(path, path.resolve())
        ]
        files.sort(key=lambda item: item.name, reverse=True)
        documents: list[MemoryDocument] = []
        for path in files[:limit]:
            if not self._contained(path.resolve()):
                continue
            text = self._read_text(path)
            documents.append(
                MemoryDocument(
                    path=self.relative_path(path),
                    title=_public_text(extract_title(text, path.stem)),
                    content=self._compact(text),
                )
            )
        return documents

    def _iter_memory_files(self, project: str | None) -> list[Path]:
        slug, roots = self._memory_file_roots(project)
        files: list[Path] = []
        seen: set[Path] = set()
        self._collect_markdown_roots(roots, files, seen)
        self._collect_todo_memory_files(slug, files, seen)
        self._collect_daily_for_scope(slug, files, seen)
        return files

    def _memory_file_roots(self, project: str | None) -> tuple[str | None, list[Path]]:
        if not project:
            return None, [self.safe_path(self.memory_root, "Projects")]
        slug = self.project_slug(project)
        roots = [
            self.safe_path(self.memory_root, "Projects", slug, "Project State.md"),
            self.safe_path(self.memory_root, "Projects", slug, "Sessions"),
            self.safe_path(self.memory_root, "Projects", slug, "Decisions"),
        ]
        return slug, roots

    def _remember_markdown_file(
        self,
        path: Path,
        files: list[Path],
        seen: set[Path],
    ) -> None:
        resolved = path.resolve()
        if resolved in seen:
            return
        if self._can_index_markdown(path, resolved):
            seen.add(resolved)
            files.append(path)

    def _can_index_markdown(self, path: Path, resolved: Path) -> bool:
        """Index a real Markdown file. Do not follow an in-vault note symlink."""
        if path.is_symlink() and self._contained(resolved) and resolved.suffix.lower() == ".md":
            return False
        if not path.is_file() or resolved.suffix.lower() != ".md":
            return False
        return self._contained(resolved)

    def _collect_markdown_roots(
        self,
        roots: list[Path],
        files: list[Path],
        seen: set[Path],
    ) -> None:
        for root in roots:
            if root.is_file() and root.resolve().suffix.lower() == ".md":
                self._remember_markdown_file(root, files, seen)
                continue
            if not root.exists() or not root.is_dir():
                continue
            for path in root.rglob("*.md"):
                self._remember_markdown_file(path, files, seen)

    def _collect_todo_memory_files(
        self,
        slug: str | None,
        files: list[Path],
        seen: set[Path],
    ) -> None:
        for path in self._iter_todo_notes():
            if self._todo_note_outside_project(path, slug):
                continue
            self._remember_markdown_file(path, files, seen)

    def _todo_note_outside_project(self, path: Path, slug: str | None) -> bool:
        if slug is None:
            return False
        text = self._read_text(path)
        fields = parse_frontmatter_fields(text)
        return not self._todo_belongs_to_project(fields, slug, text)

    def _collect_daily_for_scope(
        self,
        slug: str | None,
        files: list[Path],
        seen: set[Path],
    ) -> None:
        """Skip daily notes when a project filter is set."""
        if slug is not None:
            return
        self._collect_daily_memory_files(files, seen)

    def _collect_daily_memory_files(self, files: list[Path], seen: set[Path]) -> None:
        for path in self._iter_daily_notes():
            self._remember_markdown_file(path, files, seen)

    def _render_session_entry(
        self,
        *,
        summary: str,
        changes: Sequence[str] | None,
        decisions: Sequence[str] | None,
        open_questions: Sequence[str] | None,
        next_steps: Sequence[str] | None,
        git_info: GitInfo | None,
        now: datetime,
    ) -> str:
        git_lines: list[str] = []
        if git_info is not None:
            if git_info.repo_name:
                git_lines.append(f"Repository: {git_info.repo_name}")
            if git_info.branch:
                git_lines.append(f"Branch: {git_info.branch}")
            if git_info.short_sha:
                git_lines.append(f"Commit: {git_info.short_sha}")
            if git_info.dirty is not None:
                git_lines.append(f"Dirty: {'yes' if git_info.dirty else 'no'}")
            if git_info.changed_files:
                git_lines.append("Changed files: " + ", ".join(git_info.changed_files))
        return join_blocks(
            f"## {format_heading_time(now)}",
            section("Summary", _shield_bearer_value(summary), level=3),
            section("Git", git_lines or None, level=3),
            section("Changes", _shield_sequence(changes), level=3),
            section("Decisions", _shield_sequence(decisions), level=3),
            section("Open Questions", _shield_sequence(open_questions), level=3),
            section("Next Steps", _shield_sequence(next_steps), level=3),
        ).rstrip()

    def _compact(self, text: str) -> str:
        text = _public_text(text)
        if len(text) <= DEFAULT_CONTEXT_LIMIT:
            return text
        return text[: DEFAULT_CONTEXT_LIMIT].rstrip() + "\n..."

    def _indexable_text(self, path: Path) -> str:
        """Return note text, or empty when that note cannot be decoded."""
        try:
            return self._read_text(path)
        except VaultError:
            return ""

    def _read_text(self, path: Path) -> str:
        self._assert_inside(path)
        self._reject_in_vault_markdown_symlink(path)
        self._require_markdown_note(path)
        return _read_utf8(path)

    def _atomic_write(self, path: Path, content: str) -> None:
        self._assert_inside(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._assert_inside(path.parent)
        fd, tmp_name = tempfile.mkstemp(prefix=".odm-", suffix=".tmp", dir=path.parent)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                if not content.endswith("\n"):
                    handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        self._assert_inside(path)

    def _assert_inside(self, path: Path) -> None:
        resolved = path.resolve() if path.exists() or path.is_symlink() else path.parent.resolve()
        if not self._contained(resolved):
            raise VaultPathError("Resolved path escapes the vault")
        if path.exists() or path.is_symlink():
            if not self._contained(path.resolve()):
                raise VaultPathError("Resolved path escapes the vault")

    def _contained(self, path: Path) -> bool:
        try:
            path.relative_to(self.root)
        except ValueError:
            return False
        return True
