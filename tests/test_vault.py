from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from obsidian_dev_memory.markdown import (
    SECRET_PLACEHOLDER,
    TaskMatchError,
    find_matching_task,
)
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


def test_update_project_state_partial_rewrite_keeps_custom_and_omitted_sections(
    tmp_path: Path,
) -> None:
    vault = make_vault(tmp_path)
    vault.ensure_project("spring-auth")
    state = vault.project_state_path("spring-auth")
    state.write_text(
        "---\n"
        "type: project-state\n"
        "project: spring-auth\n"
        "updated: 2026-08-22T11:42:00-04:00\n"
        "---\n\n"
        "# Project State\n\n"
        "## Objective\n\n"
        "Ship consent auto-approval\n\n"
        "## Current State\n\n"
        "Design complete\n\n"
        "## Blocked\n\n"
        "- Waiting on review\n\n"
        "## Risk Register\n\n"
        "Custom leftover must survive\n\n"
        "## Next Steps\n\n"
        "- Write docs\n",
        encoding="utf-8",
    )
    vault.update_project_state("spring-auth", blocked=[], now=STAMP.replace(hour=15))
    text = state.read_text(encoding="utf-8")
    assert "## Objective" in text
    assert "Ship consent auto-approval" in text
    assert "## Current State" in text
    assert "Design complete" in text
    assert "## Blocked" not in text
    assert "Waiting on review" not in text
    assert "## Risk Register" in text
    assert "Custom leftover must survive" in text
    assert "## Next Steps" in text
    assert "Write docs" in text
    assert "updated: 2026-08-22T15:42:00-04:00" in text
    assert "Agent Queue.md" not in text


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


def test_read_note_redacts_password_assignment(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.ensure_project("spring-auth")
    rel = "AI Memory/Projects/spring-auth/Sessions/2026-08-22.md"
    path = vault.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = "# Session\n\nRotate password=fixture-hunter2 before merge\n"
    path.write_text(raw, encoding="utf-8")
    note = vault.read_note(rel)
    assert "fixture-hunter2" not in note["content"]
    assert SECRET_PLACEHOLDER in note["content"]
    assert "Rotate" in note["content"]
    assert path.read_text(encoding="utf-8") == raw


def test_search_memory_excerpt_redacts_password_assignment(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.ensure_project("spring-auth")
    path = (
        vault.root
        / "AI Memory"
        / "Projects"
        / "spring-auth"
        / "Sessions"
        / "2026-08-22.md"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = "# Session\n\nRotate password=fixture-hunter2 before merge\n"
    path.write_text(raw, encoding="utf-8")
    hits = vault.search_memory("Rotate", project="spring-auth")
    assert hits
    excerpt = hits[0].matching_excerpt
    assert "fixture-hunter2" not in excerpt
    assert SECRET_PLACEHOLDER in excerpt
    assert "Rotate" in excerpt
    assert path.read_text(encoding="utf-8") == raw


def test_get_project_context_redacts_password_assignment(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.ensure_project("spring-auth")
    state = vault.project_state_path("spring-auth")
    raw = (
        "# Project State\n\n"
        "## Current State\n\n"
        "Rotate password=fixture-hunter2 before merge\n"
    )
    state.write_text(raw, encoding="utf-8")
    context = vault.get_project_context("spring-auth")
    assert "fixture-hunter2" not in context.project_state
    assert SECRET_PLACEHOLDER in context.project_state
    assert "Rotate" in context.project_state
    assert state.read_text(encoding="utf-8") == raw


def test_write_redacts_unlabeled_connection_string(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    result = vault.update_project_state(
        "spring-auth",
        notes=["DSN postgres://alice:fixture-db-pass@localhost:5432/app"],
        now=STAMP,
    )
    text = (vault.root / result.path).read_text(encoding="utf-8")
    assert "fixture-db-pass" not in text
    assert SECRET_PLACEHOLDER in text
    assert "DSN" in text


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


def test_list_blocked_tasks_reads_blocked_and_blockers(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    daily = vault.root / "Daily" / "2026-08-22.md"
    daily.parent.mkdir()
    daily.write_text("# Daily\n\nDo not overwrite me\n", encoding="utf-8")
    vault.ensure_project("spring-auth")
    state = vault.project_state_path("spring-auth")
    state.write_text(
        "# Project State\n\n"
        "## Next Steps\n\n"
        "- Write docs\n\n"
        "## In Progress\n\n"
        "- Already claimed\n\n"
        "## Blocked\n\n"
        "- Waiting on review\n"
        "- Add tests\n\n"
        "## Blockers\n\n"
        "- External dependency\n"
        "- Add tests later\n",
        encoding="utf-8",
    )
    original = state.read_text(encoding="utf-8")
    listed = vault.list_blocked_tasks("spring-auth")
    assert listed.project == "spring-auth"
    assert [item.text for item in listed.tasks] == [
        "Waiting on review",
        "Add tests",
        "External dependency",
        "Add tests later",
    ]
    assert all(item.source == "blocked" for item in listed.tasks)
    assert all(item.path.endswith("Project State.md") for item in listed.tasks)
    texts = [item.text for item in listed.tasks]
    assert "Write docs" not in texts
    assert "Already claimed" not in texts
    assert state.read_text(encoding="utf-8") == original
    assert daily.read_text(encoding="utf-8") == "# Daily\n\nDo not overwrite me\n"
    with pytest.raises(TaskMatchError, match="Ambiguous"):
        find_matching_task(texts, "Add")
    empty = vault.list_blocked_tasks("missing-project")
    assert empty.tasks == []
    state.write_text(
        "# Project State\n\n"
        "## Blocked\n\n"
        "- Waiting on review\n\n"
        "## Blockers\n\n"
        "- Waiting on review\n",
        encoding="utf-8",
    )
    deduped = vault.list_blocked_tasks("spring-auth")
    assert [item.text for item in deduped.tasks] == ["Waiting on review"]


def test_list_blocked_tasks_redacts_secrets_without_rewriting(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    daily = vault.root / "Daily" / "2026-08-22.md"
    daily.parent.mkdir()
    daily.write_text("# Daily\n\nDo not overwrite me\n", encoding="utf-8")
    vault.ensure_project("spring-auth")
    state = vault.project_state_path("spring-auth")
    raw = (
        "# Project State\n\n"
        "## Blocked\n\n"
        "- Rotate password=hunter2\n"
        "- Waiting on review\n"
    )
    state.write_text(raw, encoding="utf-8")
    listed = vault.list_blocked_tasks("spring-auth")
    assert [item.text for item in listed.tasks] == [
        f"Rotate {SECRET_PLACEHOLDER}",
        "Waiting on review",
    ]
    assert "hunter2" not in listed.tasks[0].text
    assert state.read_text(encoding="utf-8") == raw
    assert "hunter2" in raw
    assert daily.read_text(encoding="utf-8") == "# Daily\n\nDo not overwrite me\n"


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
    assert claimed.queue_status == "updated"
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


def test_claim_task_reports_unchecked_when_queue_has_no_match(tmp_path: Path) -> None:
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
    assert claimed.queue_status == "unchecked"
    assert "left unchecked" in claimed.message
    assert claimed.from_section == "Next Steps"
    assert queue.read_text(encoding="utf-8") == (
        "# Agent Queue\n\n- [ ] Add tests\n- [ ] Add tests later\n"
    )


def test_claim_task_reports_unchecked_when_agent_queue_missing(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        next_steps=["Add characterization tests"],
        now=STAMP,
    )
    claimed = vault.claim_task("spring-auth", "characterization", now=STAMP)
    assert claimed.queue_updated is False
    assert claimed.queue_status == "missing"
    assert "Agent Queue missing" in claimed.message
    assert "left unchecked" in claimed.message
    assert claimed.from_section == "Next Steps"
    state = (vault.root / claimed.path).read_text(encoding="utf-8")
    assert "Add characterization tests" in state.split("## In Progress", 1)[1]
    assert not (vault.root / "AI Memory" / "Agent Queue.md").exists()


def test_claim_task_rejects_ambiguous_queue_without_writing_state(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        next_steps=["Add characterization tests for Order Status API"],
        now=STAMP,
    )
    queue_body = (
        "# Agent Queue\n\n"
        "- [ ] Add characterization tests for Order Status API #agent\n"
        "- [ ] Add characterization tests later #agent\n"
    )
    queue = _write_agent_queue(vault, queue_body)
    with pytest.raises(VaultError, match="Ambiguous"):
        vault.claim_task("spring-auth", "characterization", now=STAMP)
    state = vault.project_state_path("spring-auth").read_text(encoding="utf-8")
    assert "Add characterization tests for Order Status API" in state.split(
        "## Next Steps", 1
    )[1]
    assert "## In Progress" not in state
    assert queue.read_text(encoding="utf-8") == queue_body


def test_complete_task_rejects_ambiguous_queue_without_writing_state(
    tmp_path: Path,
) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        in_progress=["Add characterization tests for Order Status API"],
        now=STAMP,
    )
    queue_body = (
        "# Agent Queue\n\n"
        "- [ ] Add characterization tests for Order Status API #agent\n"
        "- [ ] Add characterization tests later #agent\n"
    )
    queue = _write_agent_queue(vault, queue_body)
    with pytest.raises(VaultError, match="Ambiguous"):
        vault.complete_task("spring-auth", "characterization", now=STAMP)
    state = vault.project_state_path("spring-auth").read_text(encoding="utf-8")
    assert "Add characterization tests for Order Status API" in state.split(
        "## In Progress", 1
    )[1]
    assert "## Completed" not in state
    assert queue.read_text(encoding="utf-8") == queue_body


def test_complete_task_docs_does_not_complete_write_docs_or_check_other_queue_line(
    tmp_path: Path,
) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        in_progress=["Write docs"],
        now=STAMP,
    )
    queue_body = (
        "# Agent Queue\n\n"
        "- [ ] Fix docs-drift in orch-guide #agent\n"
        "- [ ] Personal chore\n"
    )
    queue = _write_agent_queue(vault, queue_body)
    with pytest.raises(VaultError, match="Ambiguous"):
        vault.complete_task("spring-auth", "docs", now=STAMP)
    state = vault.project_state_path("spring-auth").read_text(encoding="utf-8")
    assert "Write docs" in state.split("## In Progress", 1)[1]
    assert "## Completed" not in state
    assert queue.read_text(encoding="utf-8") == queue_body


def test_claim_task_docs_does_not_claim_write_docs_or_check_other_queue_line(
    tmp_path: Path,
) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        next_steps=["Write docs"],
        now=STAMP,
    )
    queue_body = (
        "# Agent Queue\n\n- [ ] Fix docs-drift in orch-guide #agent\n"
    )
    queue = _write_agent_queue(vault, queue_body)
    with pytest.raises(VaultError, match="Ambiguous"):
        vault.claim_task("spring-auth", "docs", now=STAMP)
    state = vault.project_state_path("spring-auth").read_text(encoding="utf-8")
    assert "Write docs" in state.split("## Next Steps", 1)[1]
    assert "## In Progress" not in state
    assert queue.read_text(encoding="utf-8") == queue_body


def test_claim_task_queue_sync_uses_matched_text_not_raw_query(
    tmp_path: Path,
) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        next_steps=["Add characterization tests for Order Status API"],
        now=STAMP,
    )
    queue = _write_agent_queue(
        vault,
        "# Agent Queue\n\n"
        "- [ ] Add characterization tests for Order Status API #agent\n"
        "- [ ] Fix docs-drift in orch-guide #agent\n",
    )
    claimed = vault.claim_task("spring-auth", "characterization", now=STAMP)
    assert claimed.queue_updated is True
    assert claimed.task == "Add characterization tests for Order Status API"
    queue_text = queue.read_text(encoding="utf-8")
    assert "- [x] Add characterization tests for Order Status API #agent" in queue_text
    assert "- [ ] Fix docs-drift in orch-guide #agent" in queue_text


def test_claim_task_does_not_write_state_when_queue_write_fails(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        next_steps=["Add characterization tests"],
        now=STAMP,
    )
    queue_body = "# Agent Queue\n\n- [ ] Add characterization tests #agent\n"
    queue = _write_agent_queue(vault, queue_body)
    original = vault._atomic_write

    def boom(path: Path, content: str) -> None:
        if path == vault.agent_queue_path():
            raise OSError("queue write failed")
        original(path, content)

    vault._atomic_write = boom  # type: ignore[method-assign]
    with pytest.raises(OSError, match="queue write failed"):
        vault.claim_task("spring-auth", "characterization", now=STAMP)
    state = vault.project_state_path("spring-auth").read_text(encoding="utf-8")
    assert "Add characterization tests" in state.split("## Next Steps", 1)[1]
    assert "## In Progress" not in state
    assert queue.read_text(encoding="utf-8") == queue_body


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


def test_unblock_task_moves_blocked_to_next_steps(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    daily = vault.root / "Daily" / "2026-08-22.md"
    daily.parent.mkdir()
    daily.write_text("# Daily\n\nDo not overwrite me\n", encoding="utf-8")
    vault.ensure_project("spring-auth")
    state = vault.project_state_path("spring-auth")
    state.write_text(
        "# Project State\n\n"
        "## Objective\n\n"
        "Ship consent\n\n"
        "## Current State\n\n"
        "Design complete\n\n"
        "## Architecture\n\n"
        "- stdio MCP\n\n"
        "## Completed\n\n"
        "- Wired vault\n\n"
        "## In Progress\n\n"
        "- Add characterization tests for Order Status API\n\n"
        "## Next Steps\n\n"
        "- Document the Automations starter pack\n\n"
        "## Blocked\n\n"
        "- Waiting on review\n\n"
        "## Blockers\n\n"
        "- External dependency\n\n"
        "## Notes\n\n"
        "- Keep this\n",
        encoding="utf-8",
    )
    queue = _write_agent_queue(
        vault,
        "# Agent Queue\n\n"
        "- [ ] Waiting on review #agent\n"
        "- [ ] Personal chore\n",
    )
    unblocked = vault.unblock_task("spring-auth", "review", now=STAMP)
    assert unblocked.task == "Waiting on review"
    assert unblocked.from_section == "Blocked"
    assert unblocked.to_section == "Next Steps"
    assert unblocked.queue_updated is False
    text = (vault.root / unblocked.path).read_text(encoding="utf-8")
    assert "## Objective" in text
    assert "Ship consent" in text
    assert "stdio MCP" in text
    assert "Wired vault" in text
    assert "Keep this" in text
    next_block = text.split("## Next Steps", 1)[1].split("##", 1)[0]
    assert "Document the Automations starter pack" in next_block
    assert "Waiting on review" in next_block
    blocked_block = text.split("## Blocked", 1)[1].split("##", 1)[0]
    assert "Waiting on review" not in blocked_block
    assert "External dependency" in blocked_block
    in_progress = text.split("## In Progress", 1)[1].split("##", 1)[0]
    assert "Add characterization tests for Order Status API" in in_progress
    assert daily.read_text(encoding="utf-8") == "# Daily\n\nDo not overwrite me\n"
    assert queue.read_text(encoding="utf-8") == (
        "# Agent Queue\n\n"
        "- [ ] Waiting on review #agent\n"
        "- [ ] Personal chore\n"
    )
    remaining = vault.unblock_task("spring-auth", "External", now=STAMP)
    assert remaining.from_section == "Blocked"
    assert remaining.to_section == "Next Steps"
    text = (vault.root / remaining.path).read_text(encoding="utf-8")
    next_block = text.split("## Next Steps", 1)[1].split("##", 1)[0]
    assert "Waiting on review" in next_block
    assert "External dependency" in next_block
    assert "## Blocked" not in text
    assert daily.read_text(encoding="utf-8") == "# Daily\n\nDo not overwrite me\n"


def test_unblock_task_rejects_missing_ambiguous_and_already_open(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        next_steps=["Write docs"],
        blocked=["Add tests", "Add tests later"],
        now=STAMP,
    )
    with pytest.raises(VaultError, match="No matching"):
        vault.unblock_task("spring-auth", "missing")
    with pytest.raises(VaultError, match="Ambiguous"):
        vault.unblock_task("spring-auth", "Add")
    with pytest.raises(VaultError, match="already in next steps"):
        vault.unblock_task("spring-auth", "Write docs")


def test_unblock_task_redacts_secrets_on_rewrite(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    vault.update_project_state(
        "spring-auth",
        blocked=["Rotate password=hunter2"],
        now=STAMP,
    )
    unblocked = vault.unblock_task("spring-auth", "Rotate", now=STAMP)
    assert SECRET_PLACEHOLDER in unblocked.task
    assert "hunter2" not in unblocked.task
    text = (vault.root / unblocked.path).read_text(encoding="utf-8")
    assert "hunter2" not in text
    assert SECRET_PLACEHOLDER in text


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


EXAMPLE_TODO = """---
type: todo
id: Q-EXAMPLE
created: 2026-09-10
status: open
project: spring-auth
---

# Example leftover

Open work that lives only in TODO.

- [ ] Wire the TODO scanner
- [x] Already finished
"""


def _write_todo(vault: Vault, name: str, body: str) -> Path:
    path = vault.root / "TODO" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_list_open_tasks_reads_todo_notes_without_project_state(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    example = _write_todo(vault, "2026-09-10-example.md", EXAMPLE_TODO)
    nested = vault.root / "TODO" / "finished" / "2026-09-10-nested.md"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text(
        "---\nstatus: open\nproject: spring-auth\n---\n\n# Nested leftover\n",
        encoding="utf-8",
    )
    _write_todo(
        vault,
        "2026-09-10-other-project.md",
        "---\nstatus: open\nproject: other-app\n---\n\n# Other project work\n",
    )
    _write_todo(
        vault,
        "2026-09-10-closed.md",
        "---\nstatus: done\nproject: spring-auth\n---\n\n# Finished leftover\n",
    )
    listed = vault.list_open_tasks("spring-auth")
    assert [(item.text, item.source, item.path) for item in listed.tasks] == [
        ("Example leftover", "todo", "TODO/2026-09-10-example.md"),
        ("Wire the TODO scanner", "todo_item", "TODO/2026-09-10-example.md"),
    ]
    texts = [item.text for item in listed.tasks]
    assert "Already finished" not in texts
    assert "Nested leftover" not in texts
    assert "Other project work" not in texts
    assert "Finished leftover" not in texts
    assert example.read_text(encoding="utf-8") == EXAMPLE_TODO
    assert not (vault.root / "AI Memory" / "Agent Queue.md").exists()
    hidden_queue = vault.list_open_tasks("spring-auth", include_agent_queue=False)
    assert [item.source for item in hidden_queue.tasks] == ["todo", "todo_item"]


def test_claim_and_complete_unique_todo_note(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    example = _write_todo(vault, "2026-09-10-example.md", EXAMPLE_TODO)
    claimed = vault.claim_task("spring-auth", "Example leftover", now=STAMP)
    assert claimed.from_section == "TODO"
    assert claimed.to_section == "In Progress"
    assert claimed.task == "Example leftover"
    assert claimed.todo_updated is True
    assert claimed.todo_path == "TODO/2026-09-10-example.md"
    assert claimed.queue_updated is False
    assert claimed.queue_status == "missing"
    assert "updated TODO note" in claimed.message
    state = (vault.root / claimed.path).read_text(encoding="utf-8")
    assert "Example leftover" in state.split("## In Progress", 1)[1]
    todo_text = example.read_text(encoding="utf-8")
    assert "status: in_progress" in todo_text
    assert "- [ ] Wire the TODO scanner" in todo_text
    remaining = [item.text for item in vault.list_open_tasks("spring-auth").tasks]
    assert remaining == ["Wire the TODO scanner"]
    assert not (vault.root / "AI Memory" / "Agent Queue.md").exists()

    done = vault.complete_task("spring-auth", "Example leftover", now=STAMP)
    assert done.from_section == "In Progress"
    assert done.to_section == "Completed"
    assert done.todo_updated is True
    completed = (vault.root / done.path).read_text(encoding="utf-8")
    assert "Example leftover" in completed.split("## Completed", 1)[1]
    assert "status: done" in example.read_text(encoding="utf-8")
    assert [item.text for item in vault.list_open_tasks("spring-auth").tasks] == [
        "Wire the TODO scanner",
    ]
    assert not (vault.root / "AI Memory" / "Agent Queue.md").exists()


def test_claim_task_checks_unique_todo_checkbox(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    example = _write_todo(vault, "2026-09-10-example.md", EXAMPLE_TODO)
    claimed = vault.claim_task("spring-auth", "Wire the TODO scanner", now=STAMP)
    assert claimed.from_section == "TODO"
    assert claimed.todo_updated is True
    assert claimed.task == "Wire the TODO scanner"
    todo_text = example.read_text(encoding="utf-8")
    assert "- [x] Wire the TODO scanner" in todo_text
    assert "status: open" in todo_text
    remaining = [(item.text, item.source) for item in vault.list_open_tasks("spring-auth").tasks]
    assert remaining == [("Example leftover", "todo")]
    assert not (vault.root / "AI Memory" / "Agent Queue.md").exists()


def test_complete_task_from_todo_only_item(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    example = _write_todo(vault, "2026-09-10-example.md", EXAMPLE_TODO)
    done = vault.complete_task("spring-auth", "Example leftover", now=STAMP)
    assert done.from_section == "TODO"
    assert done.to_section == "Completed"
    assert done.todo_updated is True
    assert "status: done" in example.read_text(encoding="utf-8")
    state = (vault.root / done.path).read_text(encoding="utf-8")
    assert "Example leftover" in state.split("## Completed", 1)[1]
    assert not (vault.root / "AI Memory" / "Agent Queue.md").exists()


def test_list_open_tasks_redacts_todo_secrets_without_rewriting(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    raw = (
        "---\nstatus: open\nproject: spring-auth\n---\n\n"
        "# Rotate leftover\n\n- [ ] Rotate password=hunter2\n"
    )
    example = _write_todo(vault, "2026-09-10-example.md", raw)
    listed = vault.list_open_tasks("spring-auth")
    texts = [item.text for item in listed.tasks]
    assert "Rotate leftover" in texts
    assert any(SECRET_PLACEHOLDER in item.text for item in listed.tasks)
    assert all("hunter2" not in item.text for item in listed.tasks)
    assert example.read_text(encoding="utf-8") == raw
    claimed = vault.claim_task("spring-auth", "Rotate leftover", now=STAMP)
    assert "hunter2" not in claimed.task
    state = (vault.root / claimed.path).read_text(encoding="utf-8")
    assert "hunter2" not in state
    checked = vault.claim_task("spring-auth", "Rotate password", now=STAMP)
    assert SECRET_PLACEHOLDER in checked.task
    assert "hunter2" not in checked.task
    rewritten = (vault.root / checked.path).read_text(encoding="utf-8")
    assert "hunter2" not in rewritten
    assert SECRET_PLACEHOLDER in rewritten
    assert "hunter2" not in example.read_text(encoding="utf-8")
    assert f"- [x] Rotate {SECRET_PLACEHOLDER}" in example.read_text(encoding="utf-8")


def test_claim_task_rejects_ambiguous_todo_match(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    _write_todo(
        vault,
        "2026-09-10-example.md",
        "---\nstatus: open\nproject: spring-auth\n---\n\n"
        "# Add tests\n\n- [ ] Add tests later\n",
    )
    with pytest.raises(VaultError, match="Ambiguous"):
        vault.claim_task("spring-auth", "Add")
    assert not (vault.root / "AI Memory" / "Agent Queue.md").exists()
