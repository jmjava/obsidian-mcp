"""Non-fatal Git snapshot helpers. Uses subprocess, never a Git library."""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from obsidian_dev_memory.models import GitInfo

_GITHUB_REMOTE_RE = re.compile(
    r"github\.com[:/](?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)",
    re.IGNORECASE,
)

logger = logging.getLogger("obsidian_dev_memory")

_GIT_TIMEOUT_SECONDS = 5
_MAX_CHANGED_FILES = 20


def collect_git_context(repository_path: str | Path | None) -> GitInfo | None:
    """Return a concise Git snapshot, or ``None`` when Git is unavailable.

    Failures are non-fatal. File contents, diffs, secrets, and environment
    variables are never included.
    """
    if repository_path is None:
        return None
    raw = str(repository_path).strip()
    if not raw:
        return None

    path = Path(raw).expanduser()
    try:
        path = path.resolve()
    except OSError:
        logger.info("Unable to resolve repository path %s", raw)
        return None
    if not path.exists():
        logger.info("Repository path does not exist: %s", path)
        return None

    toplevel = _git(["rev-parse", "--show-toplevel"], cwd=path)
    if not toplevel:
        return None

    repo_root = Path(toplevel)
    branch = _git(["branch", "--show-current"], cwd=repo_root) or None
    short_sha = _git(["rev-parse", "--short", "HEAD"], cwd=repo_root) or None
    porcelain = _git(["status", "--porcelain"], cwd=repo_root)
    if porcelain is None:
        dirty = None
        changed_files: list[str] = []
    else:
        changed_files = _parse_changed_files(porcelain)
        dirty = bool(changed_files) or bool(porcelain.strip())

    origin = _git(["remote", "get-url", "origin"], cwd=repo_root)
    return GitInfo(
        repo_name=repo_root.name,
        github_repo=parse_github_remote(origin) if origin else None,
        branch=branch,
        short_sha=short_sha,
        dirty=dirty,
        changed_files=changed_files,
    )


def parse_github_remote(url: str | None) -> str | None:
    """Return ``owner/repo`` from a GitHub remote URL, or ``None``."""
    if not url:
        return None
    match = _GITHUB_REMOTE_RE.search(url.strip().removesuffix(".git"))
    if not match:
        return None
    return f"{match.group('owner')}/{match.group('repo')}"


def _git(args: list[str], *, cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.info("Git command failed: git %s (%s)", " ".join(args), exc)
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _parse_changed_files(porcelain: str) -> list[str]:
    files: list[str] = []
    for line in porcelain.splitlines():
        if not line.strip():
            continue
        payload = line[3:] if len(line) > 3 else line.strip()
        if " -> " in payload:
            payload = payload.split(" -> ", 1)[1]
        payload = payload.strip().strip('"')
        if payload and payload not in files:
            files.append(payload)
        if len(files) >= _MAX_CHANGED_FILES:
            break
    return files
