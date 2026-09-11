from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from obsidian_dev_memory.server import (
    create_server,
    list_tool_names,
    tool_append_daily_note,
    tool_block_task,
    tool_capture_work_session,
    tool_claim_task,
    tool_complete_task,
    tool_get_project_context,
    tool_list_blocked_tasks,
    tool_list_open_tasks,
    tool_read_note,
    tool_record_decision,
    tool_search_memory,
    tool_unblock_task,
    tool_update_project_state,
)
from obsidian_dev_memory.vault import Vault, VaultError, VaultPathError

STAMP = datetime(2026, 8, 22, 11, 42, tzinfo=ZoneInfo("America/New_York"))
EXPECTED_TOOLS = {
    "get_project_context",
    "capture_work_session",
    "record_decision",
    "update_project_state",
    "search_memory",
    "read_note",
    "append_daily_note",
    "list_open_tasks",
    "list_blocked_tasks",
    "claim_task",
    "complete_task",
    "block_task",
    "unblock_task",
}


def make_vault(tmp_path: Path) -> Vault:
    root = tmp_path / "vault"
    root.mkdir()
    return Vault(root)


def test_get_project_context_returns_empty_sections(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    result = tool_get_project_context(vault, "spring-auth")
    assert result["project"] == "spring-auth"
    assert result["project_state"] == ""
    assert result["recent_sessions"] == []
    assert result["recent_decisions"] == []


def test_tool_flow_writes_readable_markdown(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    tool_update_project_state(
        vault,
        "spring-auth",
        objective="Ship consent auto-approval",
        current_state="Design complete",
        now=STAMP,
    )
    tool_capture_work_session(
        vault,
        "spring-auth",
        summary="Implemented OAuth consent auto approval",
        changes=["Updated AuthorizationServerConfig"],
        repository_path=str(tmp_path / "not-a-repo"),
        now=STAMP,
    )
    decision = tool_record_decision(
        vault,
        "spring-auth",
        title="First-party auto approval",
        context="Internal clients should skip consent",
        decision="Auto-approve first-party clients only",
        now=STAMP,
    )
    context = tool_get_project_context(vault, "spring-auth")
    assert "Ship consent auto-approval" in context["project_state"]
    assert context["recent_sessions"]
    assert context["recent_decisions"]
    note = tool_read_note(vault, decision["path"])
    assert "Auto-approve first-party clients only" in note["content"]
    hits = tool_search_memory(vault, "auto-approve", project="spring-auth")
    assert hits
    daily = tool_append_daily_note(
        vault, "Reviewed consent flow", heading="Work", date="2026-08-22"
    )
    assert daily["path"] == "Daily/2026-08-22.md"


def test_read_note_and_search_redact_password_assignment(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.ensure_project("spring-auth")
    rel = "AI Memory/Projects/spring-auth/Sessions/2026-08-22.md"
    path = vault.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Session\n\nRotate password=fixture-hunter2 before merge\n",
        encoding="utf-8",
    )
    note = tool_read_note(vault, rel)
    assert "fixture-hunter2" not in note["content"]
    assert "[redacted-secret]" in note["content"]
    hits = tool_search_memory(vault, "Rotate", project="spring-auth")
    assert hits
    assert "fixture-hunter2" not in hits[0]["matching_excerpt"]
    assert "[redacted-secret]" in hits[0]["matching_excerpt"]
    state = vault.project_state_path("spring-auth")
    state.write_text(
        "# Project State\n\n## Notes\n\n- password=fixture-hunter2\n",
        encoding="utf-8",
    )
    context = tool_get_project_context(vault, "spring-auth")
    assert "fixture-hunter2" not in context["project_state"]


def test_read_note_tool_rejects_escape(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    with pytest.raises(VaultPathError):
        tool_read_note(vault, "../../etc/passwd")


def test_task_tools_claim_and_complete(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    tool_update_project_state(
        vault,
        "spring-auth",
        objective="Ship consent",
        next_steps=["Add characterization tests", "Write docs"],
        now=STAMP,
    )
    listed = tool_list_open_tasks(vault, "spring-auth")
    assert [item["text"] for item in listed["tasks"]] == [
        "Add characterization tests",
        "Write docs",
    ]
    claimed = tool_claim_task(vault, "spring-auth", "characterization", now=STAMP)
    assert claimed["from_section"] == "Next Steps"
    assert claimed["to_section"] == "In Progress"
    assert claimed["queue_updated"] is False
    assert claimed["queue_status"] == "missing"
    remaining = tool_list_open_tasks(vault, "spring-auth")
    assert [item["text"] for item in remaining["tasks"]] == ["Write docs"]
    done = tool_complete_task(vault, "spring-auth", "characterization", now=STAMP)
    assert done["to_section"] == "Completed"
    assert tool_list_open_tasks(vault, "spring-auth")["tasks"][0]["text"] == "Write docs"
    blocked = tool_block_task(vault, "spring-auth", "Write docs", now=STAMP)
    assert blocked["from_section"] == "Next Steps"
    assert blocked["to_section"] == "Blocked"
    assert blocked["queue_updated"] is False
    assert tool_list_open_tasks(vault, "spring-auth")["tasks"] == []
    listed_blocked = tool_list_blocked_tasks(vault, "spring-auth")
    assert [item["text"] for item in listed_blocked["tasks"]] == ["Write docs"]
    assert listed_blocked["tasks"][0]["source"] == "blocked"
    unblocked = tool_unblock_task(vault, "spring-auth", "Write docs", now=STAMP)
    assert unblocked["from_section"] == "Blocked"
    assert unblocked["to_section"] == "Next Steps"
    assert unblocked["queue_updated"] is False
    assert tool_list_blocked_tasks(vault, "spring-auth")["tasks"] == []
    assert tool_list_open_tasks(vault, "spring-auth")["tasks"][0]["text"] == "Write docs"


def test_task_tools_claim_reports_unchecked_when_agent_queue_missing(
    tmp_path: Path,
) -> None:
    vault = make_vault(tmp_path)
    tool_update_project_state(
        vault,
        "spring-auth",
        next_steps=["Add characterization tests", "Write docs"],
        now=STAMP,
    )
    claimed = tool_claim_task(vault, "spring-auth", "characterization", now=STAMP)
    assert claimed["queue_updated"] is False
    assert claimed["queue_status"] == "missing"
    assert "left unchecked" in claimed["message"]
    state = (vault.root / claimed["path"]).read_text(encoding="utf-8")
    assert "Add characterization tests" in state.split("## In Progress", 1)[1]
    assert not (vault.root / "AI Memory" / "Agent Queue.md").exists()


def test_task_tools_claim_rejects_ambiguous_queue(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    tool_update_project_state(
        vault,
        "spring-auth",
        next_steps=["Add characterization tests for Order Status API"],
        now=STAMP,
    )
    queue = vault.root / "AI Memory" / "Agent Queue.md"
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue_body = (
        "# Agent Queue\n\n"
        "- [ ] Add characterization tests for Order Status API #agent\n"
        "- [ ] Add characterization tests later #agent\n"
    )
    queue.write_text(queue_body, encoding="utf-8")
    with pytest.raises(VaultError, match="Ambiguous"):
        tool_claim_task(vault, "spring-auth", "characterization", now=STAMP)
    state = vault.project_state_path("spring-auth").read_text(encoding="utf-8")
    assert "Add characterization tests for Order Status API" in state.split(
        "## Next Steps", 1
    )[1]
    assert "## In Progress" not in state
    assert queue.read_text(encoding="utf-8") == queue_body


def test_task_tools_claim_checks_agent_queue(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    tool_update_project_state(
        vault,
        "spring-auth",
        next_steps=["Add characterization tests", "Write docs"],
        now=STAMP,
    )
    queue = vault.root / "AI Memory" / "Agent Queue.md"
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue.write_text(
        "# Agent Queue\n\n- [ ] Add characterization tests #agent\n- [ ] Personal chore\n",
        encoding="utf-8",
    )
    claimed = tool_claim_task(vault, "spring-auth", "characterization", now=STAMP)
    assert claimed["queue_updated"] is True
    assert claimed["queue_path"] == "AI Memory/Agent Queue.md"
    assert "- [x] Add characterization tests #agent" in queue.read_text(encoding="utf-8")
    assert "- [ ] Personal chore" in queue.read_text(encoding="utf-8")
    remaining = [item["text"] for item in tool_list_open_tasks(vault, "spring-auth")["tasks"]]
    assert remaining == ["Write docs", "Personal chore"]


def test_task_tools_list_and_claim_todo_fixture(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    example = vault.root / "TODO" / "2026-09-10-example.md"
    example.parent.mkdir()
    example.write_text(
        "---\n"
        "type: todo\n"
        "id: Q-EXAMPLE\n"
        "created: 2026-09-10\n"
        "status: open\n"
        "project: spring-auth\n"
        "---\n\n"
        "# Example leftover\n\n"
        "- [ ] Wire the TODO scanner\n",
        encoding="utf-8",
    )
    listed = tool_list_open_tasks(vault, "spring-auth")
    assert [(item["text"], item["source"], item["path"]) for item in listed["tasks"]] == [
        ("Example leftover", "todo", "TODO/2026-09-10-example.md"),
        ("Wire the TODO scanner", "todo_item", "TODO/2026-09-10-example.md"),
    ]
    claimed = tool_claim_task(vault, "spring-auth", "Example leftover", now=STAMP)
    assert claimed["from_section"] == "TODO"
    assert claimed["to_section"] == "In Progress"
    assert claimed["todo_updated"] is True
    assert claimed["queue_updated"] is False
    remaining = [item["text"] for item in tool_list_open_tasks(vault, "spring-auth")["tasks"]]
    assert remaining == ["Wire the TODO scanner"]
    assert "status: in_progress" in example.read_text(encoding="utf-8")
    assert not (vault.root / "AI Memory" / "Agent Queue.md").exists()


def test_create_server_registers_expected_tools(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    server = create_server(vault)
    names = set(list_tool_names(server))
    assert EXPECTED_TOOLS <= names


def test_merge_mcp_config_preserves_unrelated_servers(tmp_path: Path) -> None:
    dest = tmp_path / ".cursor" / "mcp.json"
    dest.parent.mkdir()
    dest.write_text(
        json.dumps({"mcpServers": {"other": {"command": "echo"}}}),
        encoding="utf-8",
    )
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "merge_mcp_config.py"
    spec = importlib.util.spec_from_file_location("merge_mcp_config", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.merge_server_config(
        dest,
        flavor="cursor",
        server_name="obsidian-dev-memory",
        server_config={"command": "uv"},
    )
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["mcpServers"]["other"]["command"] == "echo"
    assert data["mcpServers"]["obsidian-dev-memory"]["command"] == "uv"


def test_merge_mcp_config_claude_flavor_uses_mcp_servers(tmp_path: Path) -> None:
    dest = tmp_path / ".mcp.json"
    dest.write_text(
        json.dumps({"mcpServers": {"other": {"command": "echo"}}}),
        encoding="utf-8",
    )
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "merge_mcp_config.py"
    spec = importlib.util.spec_from_file_location("merge_mcp_config", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.merge_server_config(
        dest,
        flavor="claude",
        server_name="obsidian-dev-memory",
        server_config={"command": "uv", "type": "stdio"},
    )
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["mcpServers"]["other"]["command"] == "echo"
    assert data["mcpServers"]["obsidian-dev-memory"]["command"] == "uv"
    assert data["mcpServers"]["obsidian-dev-memory"]["type"] == "stdio"


def test_install_project_writes_claude_config(tmp_path: Path) -> None:
    project = tmp_path / "app"
    vault = tmp_path / "vault"
    project.mkdir()
    vault.mkdir()
    script = Path(__file__).resolve().parents[1] / "scripts" / "install-project.sh"
    subprocess.run(
        [str(script), "--project", str(project), "--vault", str(vault)],
        check=True,
        capture_output=True,
        text=True,
    )
    claude = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
    assert claude["mcpServers"]["obsidian-dev-memory"]["type"] == "stdio"
    assert claude["mcpServers"]["obsidian-dev-memory"]["env"]["OBSIDIAN_VAULT_PATH"] == str(
        vault.resolve()
    )
    rule = project / ".claude" / "rules" / "obsidian-memory.md"
    assert rule.is_file()
    assert "get_project_context" in rule.read_text(encoding="utf-8")
    assert (project / ".cursor" / "mcp.json").is_file()
    assert (project / ".vscode" / "mcp.json").is_file()
