"""Safe CRUD operations against an Obsidian Markdown vault."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from obsidian_dev_memory.git_context import collect_git_context
from obsidian_dev_memory.markdown import (
    TaskMatchError,
    append_under_heading,
    excerpt_around,
    extract_title,
    find_matching_task,
    find_task_across_sources,
    format_date,
    format_frontmatter,
    format_heading_time,
    format_iso_datetime,
    join_blocks,
    local_now,
    move_open_checkbox,
    move_task_bullet,
    normalize_task_text,
    parse_frontmatter_fields,
    parse_open_checkboxes,
    parse_open_todo_entries,
    parse_project_state,
    patch_project_state_sections,
    redact_secrets,
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


class VaultError(Exception):
    """Base error for vault operations."""


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
        if not parts:
            raise VaultPathError("A vault-relative path is required")
        raw = Path(*[str(part) for part in parts])
        if raw.is_absolute() or raw.as_posix().startswith("~"):
            raise VaultPathError("Absolute paths are not allowed as note paths")
        if any(part in {"..", ""} or part.startswith("..") for part in raw.parts):
            raise VaultPathError("Path traversal is not allowed")
        if "\x00" in raw.as_posix():
            raise VaultPathError("Invalid path")

        current = self.root
        for part in raw.parts:
            current = current / part
            if current.exists() or current.is_symlink():
                resolved = current.resolve()
                if not self._contained(resolved):
                    raise VaultPathError("Resolved path escapes the vault")

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
            f"# {redact_secrets(title.strip())}",
            section("Context", context),
            section("Decision", decision),
            section("Rationale", rationale),
            section("Consequences", consequences),
            section("Alternatives Considered", alternatives),
            section("Related Files", related_files),
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
                objective=objective,
                current_state=current_state,
                architecture=architecture,
                completed=completed,
                in_progress=in_progress,
                blocked=blocked,
                next_steps=next_steps,
                important_files=important_files,
                notes=notes,
                extra_sections=extra_sections,
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

        state_path = self.project_state_path(project)
        if state_path.exists() and state_path.is_file():
            parsed = parse_project_state(self._read_text(state_path))
            rel = self.relative_path(state_path)
            for item in parsed["next_steps"]:
                text = redact_secrets(str(item))
                key = normalize_task_text(text)
                if not key or key in seen:
                    continue
                seen.add(key)
                tasks.append(OpenTask(text=text, source="next_steps", path=rel))

        if include_agent_queue:
            queue_path = self.agent_queue_path()
            if queue_path.exists() and queue_path.is_file():
                rel = self.relative_path(queue_path)
                for item in parse_open_checkboxes(self._read_text(queue_path)):
                    text = redact_secrets(item)
                    key = normalize_task_text(text)
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    tasks.append(OpenTask(text=text, source="agent_queue", path=rel))

        for match in self._collect_todo_items(slug, note_statuses=_TODO_CLAIM_NOTE_STATUSES):
            text = redact_secrets(match.text)
            key = normalize_task_text(text)
            if not key or key in seen:
                continue
            seen.add(key)
            source = "todo" if match.kind == "note" else "todo_item"
            tasks.append(OpenTask(text=text, source=source, path=self.relative_path(match.path)))

        return OpenTaskList(project=slug, tasks=tasks)

    def list_blocked_tasks(self, project: str) -> OpenTaskList:
        slug = self.project_slug(project)
        tasks: list[OpenTask] = []
        seen: set[str] = set()

        state_path = self.project_state_path(project)
        if state_path.exists() and state_path.is_file():
            parsed = parse_project_state(self._read_text(state_path))
            rel = self.relative_path(state_path)
            for item in parsed["blocked"]:
                text = redact_secrets(str(item))
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
        parsed = self._load_project_state(project)
        in_progress = [str(item) for item in parsed["in_progress"]]
        already = self._exact_task_match(in_progress, task)
        if already is not None:
            raise VaultError(f"Task already in progress: {already}")
        next_steps = [str(item) for item in parsed["next_steps"]]
        from_section = "Next Steps"
        try:
            next_steps, in_progress, matched = move_task_bullet(
                next_steps,
                in_progress,
                task,
            )
        except TaskMatchError as exc:
            matched, from_section = self._fallback_to_external_source(project, task, exc)
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
            task_query=task,
            todo_status="in_progress",
        )

    def complete_task(
        self,
        project: str,
        task: str,
        now: datetime | None = None,
    ) -> TaskMoveResult:
        parsed = self._load_project_state(project)
        in_progress = [str(item) for item in parsed["in_progress"]]
        completed = [str(item) for item in parsed["completed"]]
        from_section = "In Progress"
        try:
            in_progress, completed, matched = move_task_bullet(
                in_progress,
                completed,
                task,
            )
        except TaskMatchError as exc:
            matched, from_section = self._fallback_to_external_source(project, task, exc)
            completed = self._append_unique_task(completed, matched)
        parsed["in_progress"] = in_progress
        parsed["completed"] = completed
        return self._rewrite_moved_task(
            project=project,
            parsed=parsed,
            matched=matched,
            from_section=from_section,
            to_section="Completed",
            message="Completed task",
            now=now,
            task_query=task,
            todo_status="done",
        )

    def block_task(
        self,
        project: str,
        task: str,
        now: datetime | None = None,
    ) -> TaskMoveResult:
        parsed = self._load_project_state(project)
        next_steps = [str(item) for item in parsed["next_steps"]]
        in_progress = [str(item) for item in parsed["in_progress"]]
        blocked = [str(item) for item in parsed["blocked"]]
        already = self._exact_task_match(blocked, task)
        if already is not None:
            raise VaultError(f"Task already blocked: {already}")
        try:
            _, from_section = find_task_across_sources(
                (("Next Steps", next_steps), ("In Progress", in_progress)),
                task,
            )
        except TaskMatchError as exc:
            raise VaultError(str(exc)) from exc
        if from_section == "Next Steps":
            next_steps, blocked, matched = move_task_bullet(next_steps, blocked, task)
        else:
            in_progress, blocked, matched = move_task_bullet(in_progress, blocked, task)
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
            task_query=task,
            sync_agent_queue=False,
        )

    def unblock_task(
        self,
        project: str,
        task: str,
        now: datetime | None = None,
    ) -> TaskMoveResult:
        parsed = self._load_project_state(project)
        next_steps = [str(item) for item in parsed["next_steps"]]
        blocked = [str(item) for item in parsed["blocked"]]
        already = self._exact_task_match(next_steps, task)
        if already is not None:
            raise VaultError(f"Task already in next steps: {already}")
        try:
            blocked, next_steps, matched = move_task_bullet(blocked, next_steps, task)
        except TaskMatchError as exc:
            raise VaultError(str(exc)) from exc
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
            task_query=task,
            sync_agent_queue=False,
        )

    def _load_project_state(
        self, project: str
    ) -> dict[str, str | list[str] | list[tuple[str, str]]]:
        path = self.project_state_path(project)
        if not path.exists() or not path.is_file():
            return parse_project_state("")
        return parse_project_state(self._read_text(path))

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

    def _matching_open_queue_item(self, task: str) -> str | None:
        path = self.agent_queue_path()
        if not path.exists() or not path.is_file():
            return None
        try:
            return find_matching_task(parse_open_checkboxes(self._read_text(path)), task)
        except TaskMatchError as exc:
            if "No matching" in str(exc):
                return None
            raise VaultError(str(exc)) from exc

    def _fallback_to_external_source(
        self,
        project: str,
        task: str,
        exc: TaskMatchError,
    ) -> tuple[str, str]:
        if "No matching" not in str(exc):
            raise VaultError(str(exc)) from exc
        queue_item = self._matching_open_queue_item(task)
        if queue_item is not None:
            return queue_item, "Agent Queue"
        todo_item = self._find_todo_match(
            project,
            task,
            note_statuses=_TODO_CLAIM_NOTE_STATUSES,
        )
        if todo_item is None:
            raise VaultError(str(exc)) from exc
        return todo_item.text, "TODO"

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
            updated, _matched = move_open_checkbox(existing, task)
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
        # report success while a matching box stays open.
        if queue_sync.body is not None:
            self._atomic_write(self.agent_queue_path(), queue_sync.body)
        written = self.update_project_state(project=project, now=now, **parsed)
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
            task=redact_secrets(matched),
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
        try:
            directory = self.safe_path(DEFAULT_TODO_ROOT)
        except VaultPathError:
            return []
        if not directory.exists() or not directory.is_dir():
            return []
        files: list[Path] = []
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            if not path.is_file() or path.suffix.lower() != ".md":
                continue
            try:
                resolved = self.safe_path(DEFAULT_TODO_ROOT, path.name)
            except VaultPathError:
                continue
            if resolved.is_file() and self._contained(resolved.resolve()):
                files.append(resolved)
        return files

    def _todo_belongs_to_project(self, fields: dict[str, str], project_slug: str) -> bool:
        raw = fields.get("project", "").strip()
        if not raw:
            return True
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
            if not self._todo_belongs_to_project(fields, slug):
                continue
            for entry_text, kind in parse_open_todo_entries(
                text,
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
            updated = set_frontmatter_field(existing, "status", status)
        if updated == existing:
            return "", None
        return self.relative_path(match.path), updated

    def search_memory(
        self,
        query: str,
        project: str | None = None,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[SearchHit]:
        terms = [term.lower() for term in re.findall(r"[A-Za-z0-9_-]+", query)]
        if not terms:
            return []
        limit = max(1, limit)
        hits: list[SearchHit] = []
        for path in self._iter_memory_files(project):
            text = self._read_text(path)
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
                    title=redact_secrets(extract_title(text, path.stem)),
                    matching_excerpt=redact_secrets(
                        excerpt_around(text, terms, limit=DEFAULT_EXCERPT_LIMIT)
                    ),
                    score=score,
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.path))
        return hits[:limit]

    def read_note(self, path: str) -> dict[str, str]:
        target = self.safe_path(path)
        if not target.exists() or not target.is_file():
            raise VaultPathError(f"Note does not exist: {path}")
        return {
            "path": self.relative_path(target),
            "content": redact_secrets(self._read_text(target)),
        }

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
        path = self.safe_path("Daily", f"{day}.md")
        existing = self._read_text(path) if path.exists() else ""
        created = not path.exists()
        updated = append_under_heading(existing, content, heading)
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
            if path.is_file() and path.suffix.lower() == ".md"
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
                    title=redact_secrets(extract_title(text, path.stem)),
                    content=self._compact(text),
                )
            )
        return documents

    def _iter_memory_files(self, project: str | None) -> list[Path]:
        if project:
            slug = self.project_slug(project)
            roots = [
                self.safe_path(self.memory_root, "Projects", slug, "Project State.md"),
                self.safe_path(self.memory_root, "Projects", slug, "Sessions"),
                self.safe_path(self.memory_root, "Projects", slug, "Decisions"),
            ]
        else:
            roots = [self.safe_path(self.memory_root, "Projects")]
        files: list[Path] = []
        for root in roots:
            if root.is_file() and root.suffix.lower() == ".md":
                files.append(root)
                continue
            if not root.exists() or not root.is_dir():
                continue
            for path in root.rglob("*.md"):
                if path.is_file() and self._contained(path.resolve()):
                    files.append(path)
        return files

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
            section("Summary", summary, level=3),
            section("Git", git_lines or None, level=3),
            section("Changes", changes, level=3),
            section("Decisions", decisions, level=3),
            section("Open Questions", open_questions, level=3),
            section("Next Steps", next_steps, level=3),
        ).rstrip()

    def _compact(self, text: str) -> str:
        text = redact_secrets(text)
        if len(text) <= DEFAULT_CONTEXT_LIMIT:
            return text
        return text[: DEFAULT_CONTEXT_LIMIT].rstrip() + "\n..."

    def _read_text(self, path: Path) -> str:
        self._assert_inside(path)
        return path.read_text(encoding="utf-8")

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
