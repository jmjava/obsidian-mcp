"""Proving tests for smoke, merge, and Agent Queue checkbox sync."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from smoke_server import evaluate_smoke

from obsidian_dev_memory.vault import Vault

REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKE = REPO_ROOT / "scripts" / "smoke-test.sh"
MERGE = REPO_ROOT / "scripts" / "merge_mcp_config.py"
STAMP = datetime(2026, 8, 22, 11, 42, tzinfo=ZoneInfo("America/New_York"))
QUEUE_ITEM = "Fix docs-drift in orch-guide #agent"


class _EmptyTools:
    def list_tools(self) -> list[object]:
        return []


class _EmptyServer:
    _tool_manager = _EmptyTools()


def _run_smoke(vault: str, *, skip_pytest: bool) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["OBSIDIAN_VAULT_PATH"] = vault
    if skip_pytest:
        env["SMOKE_SKIP_PYTEST"] = "1"
    else:
        env.pop("SMOKE_SKIP_PYTEST", None)
    return subprocess.run(
        [str(SMOKE)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_smoke_missing_vault_path_fails() -> None:
    missing = "/tmp/missing"
    assert not Path(missing).exists()
    result = _run_smoke(missing, skip_pytest=True)
    assert result.returncode != 0
    assert "does not exist" in result.stderr
    assert not Path(missing).exists()


def test_smoke_tmp_fixture_fails_when_create_server_drops_tools(tmp_path: Path) -> None:
    fixture = tmp_path / "vault"
    fixture.mkdir()

    def dropped(_vault: Vault) -> _EmptyServer:
        return _EmptyServer()

    with pytest.raises(SystemExit, match="dropped tools"):
        evaluate_smoke(str(fixture), server_factory=dropped)
    assert fixture.is_dir()


def test_smoke_tmp_fixture_registers_tools(tmp_path: Path) -> None:
    fixture = tmp_path / "vault"
    fixture.mkdir()
    result = _run_smoke(str(fixture), skip_pytest=True)
    assert result.returncode == 0, result.stderr
    assert "smoke tools ok" in result.stdout
    assert "claim_task" in result.stdout
    assert "complete_task" in result.stdout


def test_merge_cli_keeps_foreign_mcp_server(tmp_path: Path) -> None:
    dest = tmp_path / "mcp.json"
    dest.write_text(
        json.dumps({"mcpServers": {"other": {"command": "echo", "args": ["keep"]}}}) + "\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(MERGE),
            "--file",
            str(dest),
            "--flavor",
            "cursor",
            "--name",
            "obsidian-dev-memory",
            "--config-json",
            json.dumps({"command": "uv"}),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["mcpServers"]["other"]["command"] == "echo"
    assert data["mcpServers"]["other"]["args"] == ["keep"]
    assert data["mcpServers"]["obsidian-dev-memory"]["command"] == "uv"


def _queue_only_vault(tmp_path: Path) -> tuple[Vault, Path]:
    vault = Vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        objective="Ship consent",
        next_steps=["Write docs"],
        now=STAMP,
    )
    queue = tmp_path / "AI Memory" / "Agent Queue.md"
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue.write_text(
        f"# Agent Queue\n\n- [ ] {QUEUE_ITEM}\n- [ ] Personal chore\n",
        encoding="utf-8",
    )
    return vault, queue


def test_claim_queue_only_item_fails_if_box_stays_open(tmp_path: Path) -> None:
    vault, queue = _queue_only_vault(tmp_path)
    claimed = vault.claim_task("spring-auth", "docs-drift", now=STAMP)
    assert claimed.from_section == "Agent Queue"
    assert claimed.queue_updated is True
    text = queue.read_text(encoding="utf-8")
    assert f"- [x] {QUEUE_ITEM}" in text
    assert f"- [ ] {QUEUE_ITEM}" not in text
    assert "- [ ] Personal chore" in text


def test_complete_queue_only_item_fails_if_box_stays_open(tmp_path: Path) -> None:
    vault, queue = _queue_only_vault(tmp_path)
    done = vault.complete_task("spring-auth", "docs-drift", now=STAMP)
    assert done.from_section == "Agent Queue"
    assert done.queue_updated is True
    text = queue.read_text(encoding="utf-8")
    assert f"- [x] {QUEUE_ITEM}" in text
    assert f"- [ ] {QUEUE_ITEM}" not in text
    assert "- [ ] Personal chore" in text
