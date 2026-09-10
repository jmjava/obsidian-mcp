"""Typed records used by vault operations and MCP tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class GitInfo:
    """Lightweight Git snapshot. Never includes diffs or file contents."""

    repo_name: str | None = None
    branch: str | None = None
    short_sha: str | None = None
    dirty: bool | None = None
    changed_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryDocument:
    """A vault note returned as compact structured context."""

    path: str
    title: str = ""
    content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectContext:
    """Durable project memory returned by get_project_context."""

    project: str
    project_state: str = ""
    recent_sessions: list[MemoryDocument] = field(default_factory=list)
    recent_decisions: list[MemoryDocument] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "project_state": self.project_state,
            "recent_sessions": [item.to_dict() for item in self.recent_sessions],
            "recent_decisions": [item.to_dict() for item in self.recent_decisions],
        }


@dataclass(frozen=True)
class SearchHit:
    """A single local search match."""

    path: str
    title: str
    matching_excerpt: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WriteResult:
    """Result of creating or updating a vault note."""

    path: str
    created: bool = True
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpenTask:
    """One Next Step, Agent Queue checkbox, or Blocked / Blockers bullet."""

    text: str
    source: str
    path: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class OpenTaskList:
    """Tasks returned by list_open_tasks or list_blocked_tasks."""

    project: str
    tasks: list[OpenTask] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "tasks": [item.to_dict() for item in self.tasks],
        }


@dataclass(frozen=True)
class TaskMoveResult:
    """Result of claiming, completing, blocking, or unblocking a Project State task."""

    path: str
    created: bool = False
    message: str = ""
    task: str = ""
    from_section: str = ""
    to_section: str = ""
    queue_updated: bool = False
    queue_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
