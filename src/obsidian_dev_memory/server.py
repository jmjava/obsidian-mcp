"""MCP stdio server exposing Obsidian developer-memory tools."""

from __future__ import annotations

import inspect
import logging
import sys
from collections.abc import Sequence
from typing import Any

from obsidian_dev_memory.vault import Vault, VaultError

logger = logging.getLogger("obsidian_dev_memory")

_SECURITY_INSTRUCTIONS = """
Persistent engineering memory for Cursor, GitHub Copilot, and Claude.

Never persist passwords, API keys, access tokens, refresh tokens, JWT values,
private keys, .env contents, database credentials, production secrets, or
sensitive customer data. If a summary contains secret-looking material, store a
generic description instead of the literal value.

Prefer updating existing project memory rather than creating duplicate notes.
Call get_project_context before substantial work. Do not record typo fixes,
formatting-only changes, or one-line mechanical edits.
""".strip()


def _mcp_server_class() -> type:
    try:
        from mcp.server import MCPServer

        return MCPServer
    except ImportError:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP

        return FastMCP


def create_server(vault: Vault | None = None) -> Any:
    """Build the MCP server. Vault is loaded from the environment when omitted."""
    active_vault = vault or Vault.from_env()
    server_cls = _mcp_server_class()
    try:
        mcp = server_cls("obsidian-dev-memory", instructions=_SECURITY_INSTRUCTIONS)
    except TypeError:
        mcp = server_cls("obsidian-dev-memory")

    @mcp.tool()
    def get_project_context(
        project: str,
        recent_sessions: int = 5,
        recent_decisions: int = 10,
    ) -> dict[str, Any]:
        """Retrieve concise durable memory before substantial work.

        Reads Project State.md plus the newest session and decision notes.
        Returns empty sections when the project is new. Never returns the
        entire vault.
        """
        return active_vault.get_project_context(
            project,
            recent_sessions=recent_sessions,
            recent_decisions=recent_decisions,
        ).to_dict()

    @mcp.tool()
    def capture_work_session(
        project: str,
        summary: str,
        changes: list[str] | None = None,
        decisions: list[str] | None = None,
        open_questions: list[str] | None = None,
        next_steps: list[str] | None = None,
        repository_path: str | None = None,
    ) -> dict[str, Any]:
        """Capture meaningful work performed during a coding session.

        Appends a timestamped section to that day's session note. When
        repository_path is a Git repo, records branch, short SHA, and dirty
        state. Never persist secrets or full diffs.
        """
        return active_vault.capture_work_session(
            project=project,
            summary=summary,
            changes=changes,
            decisions=decisions,
            open_questions=open_questions,
            next_steps=next_steps,
            repository_path=repository_path,
        ).to_dict()

    @mcp.tool()
    def record_decision(
        project: str,
        title: str,
        context: str,
        decision: str,
        rationale: str = "",
        consequences: list[str] | None = None,
        alternatives: list[str] | None = None,
        related_files: list[str] | None = None,
    ) -> dict[str, Any]:
        """Store a durable architecture or engineering decision.

        Creates YYYY-MM-DD-<decision-slug>.md. If that file already exists,
        a numeric suffix is added instead of overwriting.
        """
        return active_vault.record_decision(
            project=project,
            title=title,
            context=context,
            decision=decision,
            rationale=rationale,
            consequences=consequences,
            alternatives=alternatives,
            related_files=related_files,
        ).to_dict()

    @mcp.tool()
    def update_project_state(
        project: str,
        objective: str = "",
        current_state: str = "",
        architecture: list[str] | None = None,
        completed: list[str] | None = None,
        in_progress: list[str] | None = None,
        blocked: list[str] | None = None,
        next_steps: list[str] | None = None,
        important_files: list[str] | None = None,
        notes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Replace the concise durable Project State.md for a project.

        This is current state, not a session log. Omit empty sections.
        """
        return active_vault.update_project_state(
            project=project,
            objective=objective,
            current_state=current_state,
            architecture=architecture,
            completed=completed,
            in_progress=in_progress,
            blocked=blocked,
            next_steps=next_steps,
            important_files=important_files,
            notes=notes,
        ).to_dict()

    @mcp.tool()
    def list_open_tasks(
        project: str,
        include_agent_queue: bool = True,
    ) -> dict[str, Any]:
        """List open Next Steps and optional Agent Queue checkboxes.

        Scans Project State Next Steps plus AI Memory/Agent Queue.md unchecked
        boxes when that note exists. Does not write vault files.
        """
        return active_vault.list_open_tasks(
            project,
            include_agent_queue=include_agent_queue,
        ).to_dict()

    @mcp.tool()
    def list_blocked_tasks(project: str) -> dict[str, Any]:
        """List Blocked or Blockers bullets from Project State.

        Scans Project State ## Blocked and ## Blockers sections. Does not
        write vault files or daily notes.
        """
        return active_vault.list_blocked_tasks(project).to_dict()

    @mcp.tool()
    def claim_task(project: str, task: str) -> dict[str, Any]:
        """Move a Next Steps or Agent Queue item to In Progress.

        Rewrites Project State.md the same way update_project_state does,
        preserving other sections. When a unique unchecked Agent Queue
        checkbox matches, that line is checked in place. Never writes
        daily notes.
        """
        return active_vault.claim_task(project=project, task=task).to_dict()

    @mcp.tool()
    def complete_task(project: str, task: str) -> dict[str, Any]:
        """Move an In Progress or Agent Queue item to Completed.

        Rewrites Project State.md the same way update_project_state does,
        preserving other sections. When a unique unchecked Agent Queue
        checkbox matches, that line is checked in place. Never writes
        daily notes.
        """
        return active_vault.complete_task(project=project, task=task).to_dict()

    @mcp.tool()
    def block_task(project: str, task: str) -> dict[str, Any]:
        """Move a Next Steps or In Progress item to Blocked.

        Rewrites Project State.md the same way update_project_state does,
        preserving other sections. Does not check Agent Queue boxes and
        never writes daily notes.
        """
        return active_vault.block_task(project=project, task=task).to_dict()

    @mcp.tool()
    def unblock_task(project: str, task: str) -> dict[str, Any]:
        """Move a Blocked or Blockers item back to Next Steps.

        Rewrites Project State.md the same way update_project_state does,
        preserving other sections. Does not check Agent Queue boxes and
        never writes daily notes.
        """
        return active_vault.unblock_task(project=project, task=task).to_dict()

    @mcp.tool()
    def search_memory(
        query: str,
        project: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search project state, sessions, and decisions with local text matching."""
        return [
            hit.to_dict()
            for hit in active_vault.search_memory(query, project=project, limit=limit)
        ]

    @mcp.tool()
    def read_note(path: str) -> dict[str, str]:
        """Read one Markdown note inside the configured Obsidian vault.

        The path must stay inside OBSIDIAN_VAULT_PATH. Absolute paths and
        traversal such as ../ are rejected.
        """
        return active_vault.read_note(path)

    @mcp.tool()
    def append_daily_note(
        content: str,
        heading: str | None = None,
        date: str | None = None,
    ) -> dict[str, Any]:
        """Append an item to Daily/YYYY-MM-DD.md without overwriting existing text."""
        return active_vault.append_daily_note(
            content=content,
            heading=heading,
            date=date,
        ).to_dict()

    return mcp


def list_tool_names(server: Any) -> list[str]:
    """Return registered tool names for tests and diagnostics."""
    return _extract_tool_names(server)


def _extract_tool_names(server: Any) -> list[str]:
    manager = getattr(server, "_tool_manager", None)
    if manager is not None and hasattr(manager, "list_tools"):
        listed = manager.list_tools()
        if listed and not inspect.isawaitable(listed):
            return [getattr(item, "name", str(item)) for item in listed]
    for attr in ("_tools", "tools"):
        manager = getattr(server, attr, None)
        if manager is None:
            continue
        if hasattr(manager, "list_tools"):
            listed = manager.list_tools()
            return [getattr(item, "name", str(item)) for item in listed]
        if hasattr(manager, "_tools") and isinstance(manager._tools, dict):
            return list(manager._tools.keys())
        if isinstance(manager, dict):
            return list(manager.keys())
    return []


def tool_get_project_context(
    vault: Vault,
    project: str,
    recent_sessions: int = 5,
    recent_decisions: int = 10,
) -> dict[str, Any]:
    return vault.get_project_context(project, recent_sessions, recent_decisions).to_dict()


def tool_capture_work_session(
    vault: Vault,
    project: str,
    summary: str,
    changes: Sequence[str] | None = None,
    decisions: Sequence[str] | None = None,
    open_questions: Sequence[str] | None = None,
    next_steps: Sequence[str] | None = None,
    repository_path: str | None = None,
    now: Any | None = None,
) -> dict[str, Any]:
    return vault.capture_work_session(
        project=project,
        summary=summary,
        changes=changes,
        decisions=decisions,
        open_questions=open_questions,
        next_steps=next_steps,
        repository_path=repository_path,
        now=now,
    ).to_dict()


def tool_record_decision(
    vault: Vault,
    project: str,
    title: str,
    context: str,
    decision: str,
    rationale: str = "",
    consequences: Sequence[str] | None = None,
    alternatives: Sequence[str] | None = None,
    related_files: Sequence[str] | None = None,
    now: Any | None = None,
) -> dict[str, Any]:
    return vault.record_decision(
        project=project,
        title=title,
        context=context,
        decision=decision,
        rationale=rationale,
        consequences=consequences,
        alternatives=alternatives,
        related_files=related_files,
        now=now,
    ).to_dict()


def tool_update_project_state(vault: Vault, project: str, **kwargs: Any) -> dict[str, Any]:
    return vault.update_project_state(project=project, **kwargs).to_dict()


def tool_list_open_tasks(
    vault: Vault,
    project: str,
    include_agent_queue: bool = True,
) -> dict[str, Any]:
    return vault.list_open_tasks(project, include_agent_queue=include_agent_queue).to_dict()


def tool_list_blocked_tasks(vault: Vault, project: str) -> dict[str, Any]:
    return vault.list_blocked_tasks(project).to_dict()


def tool_claim_task(
    vault: Vault,
    project: str,
    task: str,
    now: Any | None = None,
) -> dict[str, Any]:
    return vault.claim_task(project=project, task=task, now=now).to_dict()


def tool_complete_task(
    vault: Vault,
    project: str,
    task: str,
    now: Any | None = None,
) -> dict[str, Any]:
    return vault.complete_task(project=project, task=task, now=now).to_dict()


def tool_block_task(
    vault: Vault,
    project: str,
    task: str,
    now: Any | None = None,
) -> dict[str, Any]:
    return vault.block_task(project=project, task=task, now=now).to_dict()


def tool_unblock_task(
    vault: Vault,
    project: str,
    task: str,
    now: Any | None = None,
) -> dict[str, Any]:
    return vault.unblock_task(project=project, task=task, now=now).to_dict()


def tool_search_memory(
    vault: Vault,
    query: str,
    project: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    return [hit.to_dict() for hit in vault.search_memory(query, project=project, limit=limit)]


def tool_read_note(vault: Vault, path: str) -> dict[str, str]:
    return vault.read_note(path)


def tool_append_daily_note(
    vault: Vault,
    content: str,
    heading: str | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    return vault.append_daily_note(content=content, heading=heading, date=date).to_dict()


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )


def main() -> None:
    """Launch the MCP stdio server. Diagnostic logs go to stderr only."""
    _configure_logging()
    try:
        mcp = create_server()
    except VaultError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    try:
        mcp.run(transport="stdio")
    except TypeError:
        mcp.run()
