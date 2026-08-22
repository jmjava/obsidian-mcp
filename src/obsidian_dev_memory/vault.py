"""Safe CRUD operations against an Obsidian Markdown vault."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from obsidian_dev_memory.git_context import collect_git_context
from obsidian_dev_memory.markdown import (
    append_under_heading,
    excerpt_around,
    extract_title,
    format_date,
    format_frontmatter,
    format_heading_time,
    format_iso_datetime,
    join_blocks,
    local_now,
    redact_secrets,
    section,
    slugify,
)
from obsidian_dev_memory.models import (
    GitInfo,
    MemoryDocument,
    ProjectContext,
    SearchHit,
    WriteResult,
)

DEFAULT_MEMORY_ROOT = "AI Memory"
DEFAULT_CONTEXT_LIMIT = 4000
DEFAULT_SEARCH_LIMIT = 20
DEFAULT_EXCERPT_LIMIT = 240


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
        objective: str = "",
        current_state: str = "",
        architecture: Sequence[str] | None = None,
        completed: Sequence[str] | None = None,
        in_progress: Sequence[str] | None = None,
        blocked: Sequence[str] | None = None,
        next_steps: Sequence[str] | None = None,
        important_files: Sequence[str] | None = None,
        notes: Sequence[str] | None = None,
        now: datetime | None = None,
    ) -> WriteResult:
        self.ensure_project(project)
        stamp = local_now(now)
        slug = self.project_slug(project)
        path = self.project_state_path(project)
        created = not path.exists()
        body = join_blocks(
            format_frontmatter(
                {
                    "type": "project-state",
                    "project": slug,
                    "updated": format_iso_datetime(stamp),
                }
            ),
            "# Project State",
            section("Objective", objective),
            section("Current State", current_state),
            section("Architecture", architecture),
            section("Completed", completed),
            section("In Progress", in_progress),
            section("Blocked", blocked),
            section("Next Steps", next_steps),
            section("Important Files", important_files),
            section("Notes", notes),
        )
        self._atomic_write(path, body)
        return WriteResult(
            path=self.relative_path(path),
            created=created,
            message="Updated project state",
        )

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
                    title=extract_title(text, path.stem),
                    matching_excerpt=excerpt_around(
                        text, terms, limit=DEFAULT_EXCERPT_LIMIT
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
        return {"path": self.relative_path(target), "content": self._read_text(target)}

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
                    title=extract_title(text, path.stem),
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
