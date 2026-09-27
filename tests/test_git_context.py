from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from obsidian_dev_memory.git_context import collect_git_context
from obsidian_dev_memory.vault import Vault


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample-repo"
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "dev@example.com")
    _run_git(repo, "config", "user.name", "Dev")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _run_git(repo, "add", "README.md")
    _run_git(repo, "commit", "-m", "initial")
    return repo


def test_collects_branch_and_sha_for_clean_repo(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    info = collect_git_context(repo)
    assert info is not None
    assert info.repo_name == "sample-repo"
    assert info.branch
    assert info.short_sha
    assert info.dirty is False
    assert info.changed_files == []


def test_detects_dirty_repo_and_changed_files(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "new.txt").write_text("changed\n", encoding="utf-8")
    info = collect_git_context(str(repo))
    assert info is not None
    assert info.dirty is True
    assert "new.txt" in info.changed_files


def test_non_git_path_is_non_fatal(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert collect_git_context(plain) is None
    assert collect_git_context(tmp_path / "missing") is None
    assert collect_git_context(None) is None


def test_session_note_caps_changed_files_and_omits_bodies(tmp_path: Path) -> None:
    """A dirty tree records at most 20 paths and never the file bodies."""
    repo = _init_repo(tmp_path)
    names = [f"file-{index:02d}.txt" for index in range(21)]
    for name in names:
        (repo / name).write_text(f"SECRET-BODY-{name}\n", encoding="utf-8")
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault = Vault(vault_root)
    result = vault.capture_work_session(
        "spring-auth",
        summary="Snapshot stays short",
        repository_path=str(repo),
        now=datetime(2026, 8, 22, 11, 42, tzinfo=ZoneInfo("America/New_York")),
    )
    text = (vault_root / result.path).read_text(encoding="utf-8")
    changed_line = next(
        line for line in text.splitlines() if line.startswith("- Changed files: ")
    )
    listed = [
        part.strip() for part in changed_line.removeprefix("- Changed files: ").split(",")
    ]
    assert len(listed) == 20
    assert listed[0] == "file-00.txt"
    assert "file-20.txt" not in listed
    assert set(listed) < set(names)
    for name in names:
        assert f"SECRET-BODY-{name}" not in text
