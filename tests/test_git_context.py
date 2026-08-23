from __future__ import annotations

import subprocess
from pathlib import Path

from obsidian_dev_memory.git_context import collect_git_context, parse_github_remote


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


def test_parses_github_remote_urls() -> None:
    assert parse_github_remote("git@github.com:jmjava/obsidian-mcp.git") == (
        "jmjava/obsidian-mcp"
    )
    assert parse_github_remote("https://github.com/jmjava/obsidian-mcp.git") == (
        "jmjava/obsidian-mcp"
    )
    assert parse_github_remote("https://example.com/other.git") is None


def test_collects_github_repo_from_origin(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run_git(repo, "remote", "add", "origin", "https://github.com/acme/widgets.git")
    info = collect_git_context(repo)
    assert info is not None
    assert info.github_repo == "acme/widgets"


def test_non_git_path_is_non_fatal(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert collect_git_context(plain) is None
    assert collect_git_context(tmp_path / "missing") is None
    assert collect_git_context(None) is None
