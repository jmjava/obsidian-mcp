from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from obsidian_dev_memory.git_context import collect_git_context


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


def test_snapshot_does_not_run_repository_fsmonitor(tmp_path: Path) -> None:
    """A snapshot must not execute a repository-configured fsmonitor command."""
    repo = _init_repo(tmp_path)
    marker = tmp_path / "fsmonitor-ran"
    script = tmp_path / "fsmonitor.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    _run_git(repo, "config", "core.fsmonitor", str(script))
    info = collect_git_context(repo)
    assert info is not None
    assert info.dirty is False
    assert info.short_sha
    assert not marker.exists()


def test_snapshot_does_not_rewrite_the_index(tmp_path: Path) -> None:
    """A snapshot must not update the Git index while reading status."""
    repo = _init_repo(tmp_path)
    index = repo / ".git" / "index"
    future = time.time() + 5
    os.utime(repo / "README.md", (future, future))
    before = index.read_bytes()
    info = collect_git_context(repo)
    assert info is not None
    assert info.dirty is False
    assert info.short_sha
    assert index.read_bytes() == before


def test_snapshot_ignores_ambient_git_dir(tmp_path: Path, monkeypatch) -> None:
    """An ambient GIT_DIR must not replace the requested repository."""
    target = _init_repo(tmp_path)
    target_sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=target,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    other = tmp_path / "other-repo"
    other.mkdir()
    _run_git(other, "init", "-b", "other-branch")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    info = collect_git_context(target)
    assert info is not None
    assert info.repo_name == "sample-repo"
    assert info.branch != "other-branch"
    assert info.short_sha == target_sha
    assert info.dirty is False


def test_snapshot_ignores_ambient_git_work_tree(tmp_path: Path, monkeypatch) -> None:
    """An ambient GIT_WORK_TREE must not replace the requested repository."""
    target = _init_repo(tmp_path)
    target_sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=target,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    other = tmp_path / "other-tree"
    other.mkdir()
    (other / "other-file.txt").write_text("from other\n", encoding="utf-8")
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    info = collect_git_context(target)
    assert info is not None
    assert info.repo_name == "sample-repo"
    assert info.repo_name != other.name
    assert info.short_sha == target_sha
    assert info.branch
    assert info.dirty is False


def test_non_git_path_is_non_fatal(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert collect_git_context(plain) is None
    assert collect_git_context(tmp_path / "missing") is None
    assert collect_git_context(None) is None
