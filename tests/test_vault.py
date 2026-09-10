from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from obsidian_dev_memory.markdown import SECRET_PLACEHOLDER
from obsidian_dev_memory.vault import Vault, VaultError, VaultPathError

STAMP = datetime(2026, 8, 22, 11, 42, tzinfo=ZoneInfo("America/New_York"))


def make_vault(tmp_path: Path) -> Vault:
    root = tmp_path / "vault"
    root.mkdir()
    return Vault(root)


def test_creates_project_directories(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    project_dir = vault.ensure_project("Spring Auth")
    assert project_dir.name == "spring-auth"
    assert (project_dir / "Sessions").is_dir()
    assert (project_dir / "Decisions").is_dir()


def test_writes_project_state(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    result = vault.update_project_state(
        "spring-auth",
        objective="Ship consent auto-approval",
        current_state="Implementing first-party bypass",
        blocked=[],
        now=STAMP,
    )
    path = vault.root / result.path
    text = path.read_text(encoding="utf-8")
    assert path.name == "Project State.md"
    assert "type: project-state" in text
    assert "updated: 2026-08-22T11:42:00-04:00" in text
    assert "## Objective" in text
    assert "## Blocked" not in text


def test_appends_session(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    first = vault.capture_work_session(
        "spring-auth",
        summary="Implemented OAuth consent auto approval",
        changes=["Updated AuthorizationServerConfig"],
        decisions=["Auto approval applies only to first-party clients"],
        open_questions=[],
        now=STAMP,
    )
    second = vault.capture_work_session(
        "spring-auth",
        summary="Added tests",
        now=STAMP.replace(hour=15),
    )
    path = vault.root / first.path
    text = path.read_text(encoding="utf-8")
    assert first.path.endswith("Sessions/2026-08-22.md")
    assert second.path == first.path
    h2 = [
        line
        for line in text.splitlines()
        if line.startswith("## ") and not line.startswith("###")
    ]
    assert len(h2) == 2
    assert "### Summary" in text
    assert "### Open Questions" not in text
    assert "Implemented OAuth consent auto approval" in text
    assert "Added tests" in text


def test_writes_decision_and_avoids_overwrite(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    first = vault.record_decision(
        "spring-auth",
        title="Use PKCE",
        context="Public clients need proof of possession",
        decision="Require PKCE for public clients",
        now=STAMP,
    )
    second = vault.record_decision(
        "spring-auth",
        title="Use PKCE",
        context="Same slug collision",
        decision="Keep the first file and write a suffix",
        now=STAMP,
    )
    assert first.path.endswith("Decisions/2026-08-22-use-pkce.md")
    assert second.path.endswith("Decisions/2026-08-22-use-pkce-2.md")
    original = (vault.root / first.path).read_text(encoding="utf-8")
    assert "Require PKCE for public clients" in original
    assert "suffix" not in original
    assert "numeric suffix" in second.message


def test_reads_note(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state("spring-auth", objective="Remember this", now=STAMP)
    note = vault.read_note("AI Memory/Projects/spring-auth/Project State.md")
    assert "Remember this" in note["content"]


def test_appends_daily_note(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    first = vault.append_daily_note("Morning review", heading="Work", now=STAMP)
    vault.append_daily_note("Afternoon review", heading="Work", now=STAMP)
    path = vault.root / first.path
    text = path.read_text(encoding="utf-8")
    assert first.path == "Daily/2026-08-22.md"
    assert text.count("Morning review") == 1
    assert "Afternoon review" in text


def test_search_finds_known_content(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        objective="PKCE for public clients",
        now=STAMP,
    )
    hits = vault.search_memory("PKCE", project="spring-auth")
    assert hits
    assert hits[0].path.endswith("Project State.md")
    assert "PKCE" in hits[0].matching_excerpt
    assert len(hits[0].matching_excerpt) <= 280


def test_rejects_parent_traversal(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("nope\n", encoding="utf-8")
    with pytest.raises(VaultPathError, match="traversal"):
        vault.read_note("../secret.txt")


def test_rejects_absolute_paths(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("nope\n", encoding="utf-8")
    with pytest.raises(VaultPathError, match="Absolute"):
        vault.read_note(str(secret))


def test_prevents_escaping_vault_root_via_symlink(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("classified\n", encoding="utf-8")
    (vault.root / "leak").symlink_to(outside)
    with pytest.raises(VaultPathError, match="escapes"):
        vault.read_note("leak/secret.txt")


def test_list_open_tasks_reads_next_steps_and_agent_queue(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        objective="Ship consent",
        next_steps=[
            "Add characterization tests for Order Status API",
            "Document the Automations starter pack",
        ],
        in_progress=["Already claimed"],
        now=STAMP,
    )
    queue = vault.root / "AI Memory" / "Agent Queue.md"
    queue.write_text(
        "# Agent Queue\n\n"
        "- [ ] Add characterization tests for Order Status API #agent\n"
        "- [ ] Fix docs-drift in orch-guide #agent\n"
        "- [x] Finished item #agent\n",
        encoding="utf-8",
    )
    listed = vault.list_open_tasks("spring-auth")
    texts = [item.text for item in listed.tasks]
    sources = {item.text: item.source for item in listed.tasks}
    assert "Add characterization tests for Order Status API" in texts
    assert sources["Add characterization tests for Order Status API"] == "next_steps"
    assert "Fix docs-drift in orch-guide #agent" in texts
    assert sources["Fix docs-drift in orch-guide #agent"] == "agent_queue"
    assert "Already claimed" not in texts
    assert "Finished item #agent" not in texts
    hidden = vault.list_open_tasks("spring-auth", include_agent_queue=False)
    assert all(item.source == "next_steps" for item in hidden.tasks)


def test_claim_and_complete_move_next_step_bullets(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    daily = vault.root / "Daily" / "2026-08-22.md"
    daily.parent.mkdir()
    daily.write_text("# Daily\n\nDo not overwrite me\n", encoding="utf-8")
    vault.update_project_state(
        "spring-auth",
        objective="Ship consent",
        current_state="Design complete",
        architecture=["stdio MCP"],
        completed=["Wired vault"],
        in_progress=[],
        next_steps=[
            "Add characterization tests for Order Status API",
            "Document the Automations starter pack",
        ],
        notes=["Keep this"],
        now=STAMP,
    )
    claimed = vault.claim_task(
        "spring-auth",
        "characterization",
        now=STAMP.replace(hour=12),
    )
    assert claimed.task == "Add characterization tests for Order Status API"
    assert claimed.from_section == "Next Steps"
    assert claimed.to_section == "In Progress"
    text = (vault.root / claimed.path).read_text(encoding="utf-8")
    assert "## Objective" in text
    assert "Ship consent" in text
    assert "stdio MCP" in text
    assert "Wired vault" in text
    assert "Keep this" in text
    assert "- Add characterization tests for Order Status API" in text
    next_block = text.split("## Next Steps", 1)[1]
    assert "characterization" not in next_block
    assert "Document the Automations starter pack" in next_block
    in_progress = text.split("## In Progress", 1)[1].split("##", 1)[0]
    assert "Add characterization tests for Order Status API" in in_progress
    assert daily.read_text(encoding="utf-8") == "# Daily\n\nDo not overwrite me\n"

    completed = vault.complete_task(
        "spring-auth",
        "characterization",
        now=STAMP.replace(hour=13),
    )
    assert completed.from_section == "In Progress"
    assert completed.to_section == "Completed"
    text = (vault.root / completed.path).read_text(encoding="utf-8")
    completed_block = text.split("## Completed", 1)[1].split("##", 1)[0]
    assert "Wired vault" in completed_block
    assert "Add characterization tests for Order Status API" in completed_block
    assert "## In Progress" not in text
    assert daily.read_text(encoding="utf-8") == "# Daily\n\nDo not overwrite me\n"


def test_claim_task_rejects_missing_and_already_claimed(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        next_steps=["Add characterization tests"],
        in_progress=["Document the Automations starter pack"],
        now=STAMP,
    )
    with pytest.raises(VaultError, match="No matching"):
        vault.claim_task("spring-auth", "missing")
    with pytest.raises(VaultError, match="already in progress"):
        vault.claim_task("spring-auth", "Document the Automations starter pack")


def test_claim_task_redacts_secrets_on_rewrite(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        next_steps=["Rotate password=hunter2"],
        now=STAMP,
    )
    claimed = vault.claim_task("spring-auth", "Rotate", now=STAMP)
    assert SECRET_PLACEHOLDER in claimed.task
    assert "hunter2" not in claimed.task
    text = (vault.root / claimed.path).read_text(encoding="utf-8")
    assert "hunter2" not in text
    assert SECRET_PLACEHOLDER in text


def _write_agent_queue(vault: Vault, body: str) -> Path:
    queue = vault.root / "AI Memory" / "Agent Queue.md"
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue.write_text(body, encoding="utf-8")
    return queue


def test_claim_task_checks_matching_agent_queue_checkbox(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    daily = vault.root / "Daily" / "2026-08-22.md"
    daily.parent.mkdir()
    daily.write_text("# Daily\n\nDo not overwrite me\n", encoding="utf-8")
    vault.update_project_state(
        "spring-auth",
        objective="Ship consent",
        current_state="Design complete",
        architecture=["stdio MCP"],
        completed=["Wired vault"],
        next_steps=[
            "Add characterization tests for Order Status API",
            "Document the Automations starter pack",
        ],
        notes=["Keep this"],
        now=STAMP,
    )
    queue = _write_agent_queue(
        vault,
        "# Agent Queue\n\n"
        "- [ ] Add characterization tests for Order Status API #agent\n"
        "- [ ] Fix docs-drift in orch-guide #agent\n"
        "- [x] Finished item #agent\n",
    )
    claimed = vault.claim_task("spring-auth", "characterization", now=STAMP)
    assert claimed.queue_updated is True
    assert claimed.queue_path == "AI Memory/Agent Queue.md"
    assert "checked Agent Queue item" in claimed.message
    text = (vault.root / claimed.path).read_text(encoding="utf-8")
    assert "Ship consent" in text
    assert "stdio MCP" in text
    assert "Wired vault" in text
    assert "Keep this" in text
    assert "Document the Automations starter pack" in text
    queue_text = queue.read_text(encoding="utf-8")
    assert "- [x] Add characterization tests for Order Status API #agent" in queue_text
    assert "- [ ] Fix docs-drift in orch-guide #agent" in queue_text
    assert "- [x] Finished item #agent" in queue_text
    assert daily.read_text(encoding="utf-8") == "# Daily\n\nDo not overwrite me\n"
    listed = vault.list_open_tasks("spring-auth")
    assert [item.text for item in listed.tasks] == [
        "Document the Automations starter pack",
        "Fix docs-drift in orch-guide #agent",
    ]


def test_claim_task_from_queue_only_item(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        objective="Ship consent",
        next_steps=["Write docs"],
        notes=["Keep this"],
        now=STAMP,
    )
    queue = _write_agent_queue(
        vault,
        "# Agent Queue\n\n- [ ] Fix docs-drift in orch-guide #agent\n- [ ] Personal chore\n",
    )
    claimed = vault.claim_task("spring-auth", "docs-drift", now=STAMP)
    assert claimed.from_section == "Agent Queue"
    assert claimed.to_section == "In Progress"
    assert claimed.task == "Fix docs-drift in orch-guide #agent"
    assert claimed.queue_updated is True
    text = (vault.root / claimed.path).read_text(encoding="utf-8")
    assert "## Objective" in text
    assert "Write docs" in text.split("## Next Steps", 1)[1]
    in_progress = text.split("## In Progress", 1)[1].split("##", 1)[0]
    assert "Fix docs-drift in orch-guide #agent" in in_progress
    assert "Keep this" in text
    queue_text = queue.read_text(encoding="utf-8")
    assert "- [x] Fix docs-drift in orch-guide #agent" in queue_text
    assert "- [ ] Personal chore" in queue_text


def test_complete_task_checks_matching_agent_queue_checkbox(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    daily = vault.root / "Daily" / "2026-08-22.md"
    daily.parent.mkdir()
    daily.write_text("# Daily\n\nDo not overwrite me\n", encoding="utf-8")
    vault.update_project_state(
        "spring-auth",
        objective="Ship consent",
        completed=["Wired vault"],
        in_progress=["Add characterization tests for Order Status API"],
        next_steps=["Document the Automations starter pack"],
        notes=["Keep this"],
        now=STAMP,
    )
    queue = _write_agent_queue(
        vault,
        "# Agent Queue\n\n"
        "- [ ] Add characterization tests for Order Status API #agent\n"
        "- [ ] Fix docs-drift in orch-guide #agent\n",
    )
    done = vault.complete_task("spring-auth", "characterization", now=STAMP)
    assert done.from_section == "In Progress"
    assert done.to_section == "Completed"
    assert done.queue_updated is True
    text = (vault.root / done.path).read_text(encoding="utf-8")
    completed_block = text.split("## Completed", 1)[1].split("##", 1)[0]
    assert "Wired vault" in completed_block
    assert "Add characterization tests for Order Status API" in completed_block
    assert "Document the Automations starter pack" in text
    assert "Keep this" in text
    assert "## In Progress" not in text
    queue_text = queue.read_text(encoding="utf-8")
    assert "- [x] Add characterization tests for Order Status API #agent" in queue_text
    assert "- [ ] Fix docs-drift in orch-guide #agent" in queue_text
    assert daily.read_text(encoding="utf-8") == "# Daily\n\nDo not overwrite me\n"


def test_complete_task_from_queue_only_item(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        objective="Ship consent",
        next_steps=["Write docs"],
        now=STAMP,
    )
    _write_agent_queue(
        vault,
        "# Agent Queue\n\n- [ ] Fix docs-drift in orch-guide #agent\n",
    )
    done = vault.complete_task("spring-auth", "docs-drift", now=STAMP)
    assert done.from_section == "Agent Queue"
    assert done.to_section == "Completed"
    assert done.queue_updated is True
    text = (vault.root / done.path).read_text(encoding="utf-8")
    assert "Write docs" in text
    assert "Fix docs-drift in orch-guide #agent" in text.split("## Completed", 1)[1]


def test_claim_task_redacts_secrets_in_agent_queue(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        next_steps=["Rotate password=hunter2"],
        now=STAMP,
    )
    queue = _write_agent_queue(
        vault,
        "# Agent Queue\n\n- [ ] Rotate password=hunter2 #agent\n- [ ] Keep this\n",
    )
    claimed = vault.claim_task("spring-auth", "Rotate", now=STAMP)
    assert SECRET_PLACEHOLDER in claimed.task
    assert "hunter2" not in claimed.task
    state = (vault.root / claimed.path).read_text(encoding="utf-8")
    assert "hunter2" not in state
    queue_text = queue.read_text(encoding="utf-8")
    assert "hunter2" not in queue_text
    assert SECRET_PLACEHOLDER in queue_text
    assert "- [ ] Keep this" in queue_text


def test_claim_task_rejects_ambiguous_queue_only_match(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        next_steps=["Write docs"],
        now=STAMP,
    )
    queue = _write_agent_queue(
        vault,
        "# Agent Queue\n\n- [ ] Add tests\n- [ ] Add tests later\n",
    )
    with pytest.raises(VaultError, match="Ambiguous"):
        vault.claim_task("spring-auth", "Add")
    assert queue.read_text(encoding="utf-8") == (
        "# Agent Queue\n\n- [ ] Add tests\n- [ ] Add tests later\n"
    )


def test_claim_task_skips_queue_when_match_is_not_unique(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        next_steps=["Add characterization tests"],
        now=STAMP,
    )
    queue = _write_agent_queue(
        vault,
        "# Agent Queue\n\n- [ ] Add tests\n- [ ] Add tests later\n",
    )
    claimed = vault.claim_task("spring-auth", "characterization", now=STAMP)
    assert claimed.queue_updated is False
    assert claimed.from_section == "Next Steps"
    assert queue.read_text(encoding="utf-8") == (
        "# Agent Queue\n\n- [ ] Add tests\n- [ ] Add tests later\n"
    )


def test_block_task_moves_next_step_and_in_progress(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    daily = vault.root / "Daily" / "2026-08-22.md"
    daily.parent.mkdir()
    daily.write_text("# Daily\n\nDo not overwrite me\n", encoding="utf-8")
    vault.update_project_state(
        "spring-auth",
        objective="Ship consent",
        current_state="Design complete",
        architecture=["stdio MCP"],
        completed=["Wired vault"],
        in_progress=["Add characterization tests for Order Status API"],
        next_steps=["Document the Automations starter pack"],
        notes=["Keep this"],
        now=STAMP,
    )
    queue = _write_agent_queue(
        vault,
        "# Agent Queue\n\n"
        "- [ ] Document the Automations starter pack #agent\n"
        "- [ ] Personal chore\n",
    )
    blocked = vault.block_task("spring-auth", "Automations", now=STAMP)
    assert blocked.task == "Document the Automations starter pack"
    assert blocked.from_section == "Next Steps"
    assert blocked.to_section == "Blocked"
    assert blocked.queue_updated is False
    text = (vault.root / blocked.path).read_text(encoding="utf-8")
    assert "## Objective" in text
    assert "Ship consent" in text
    assert "stdio MCP" in text
    assert "Wired vault" in text
    assert "Keep this" in text
    blocked_block = text.split("## Blocked", 1)[1].split("##", 1)[0]
    assert "Document the Automations starter pack" in blocked_block
    assert "## Next Steps" not in text
    in_progress = text.split("## In Progress", 1)[1].split("##", 1)[0]
    assert "Add characterization tests for Order Status API" in in_progress
    assert daily.read_text(encoding="utf-8") == "# Daily\n\nDo not overwrite me\n"
    assert queue.read_text(encoding="utf-8") == (
        "# Agent Queue\n\n"
        "- [ ] Document the Automations starter pack #agent\n"
        "- [ ] Personal chore\n"
    )

    claimed_blocked = vault.block_task("spring-auth", "characterization", now=STAMP)
    assert claimed_blocked.from_section == "In Progress"
    assert claimed_blocked.to_section == "Blocked"
    text = (vault.root / claimed_blocked.path).read_text(encoding="utf-8")
    blocked_block = text.split("## Blocked", 1)[1].split("##", 1)[0]
    assert "Document the Automations starter pack" in blocked_block
    assert "Add characterization tests for Order Status API" in blocked_block
    assert "## In Progress" not in text
    assert daily.read_text(encoding="utf-8") == "# Daily\n\nDo not overwrite me\n"


def test_block_task_rejects_missing_ambiguous_and_already_blocked(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        next_steps=["Add characterization tests", "Add docs"],
        in_progress=["Add review notes"],
        blocked=["Waiting on review"],
        now=STAMP,
    )
    with pytest.raises(VaultError, match="No matching"):
        vault.block_task("spring-auth", "missing")
    with pytest.raises(VaultError, match="Ambiguous"):
        vault.block_task("spring-auth", "Add")
    with pytest.raises(VaultError, match="already blocked"):
        vault.block_task("spring-auth", "Waiting on review")


def test_block_task_redacts_secrets_on_rewrite(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        in_progress=["Rotate password=hunter2"],
        now=STAMP,
    )
    blocked = vault.block_task("spring-auth", "Rotate", now=STAMP)
    assert SECRET_PLACEHOLDER in blocked.task
    assert "hunter2" not in blocked.task
    text = (vault.root / blocked.path).read_text(encoding="utf-8")
    assert "hunter2" not in text
    assert SECRET_PLACEHOLDER in text


def test_invalid_daily_date_is_rejected(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    with pytest.raises(VaultError, match="YYYY-MM-DD"):
        vault.append_daily_note("x", date="tomorrow")
