from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from obsidian_dev_memory.server import (
    create_server,
    list_tool_names,
    tool_append_daily_note,
    tool_capture_work_session,
    tool_get_project_context,
    tool_read_note,
    tool_record_decision,
    tool_search_memory,
    tool_update_project_state,
)
from obsidian_dev_memory.vault import Vault, VaultPathError

STAMP = datetime(2026, 8, 22, 11, 42, tzinfo=ZoneInfo("America/New_York"))
EXPECTED_TOOLS = {
    "get_project_context",
    "capture_work_session",
    "record_decision",
    "update_project_state",
    "search_memory",
    "read_note",
    "append_daily_note",
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


def test_read_note_tool_rejects_escape(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    with pytest.raises(VaultPathError):
        tool_read_note(vault, "../../etc/passwd")


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
