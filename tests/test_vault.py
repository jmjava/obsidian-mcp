from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

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
    assert text.count("## ") == 2
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


def test_invalid_daily_date_is_rejected(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    with pytest.raises(VaultError, match="YYYY-MM-DD"):
        vault.append_daily_note("x", date="tomorrow")
