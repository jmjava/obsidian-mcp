"""Git helpers for diff and change-frequency gates."""

from __future__ import annotations

import subprocess
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def git_text(args: list[str], root: Path) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "git failed"
        raise RuntimeError(detail)
    return completed.stdout


def ref_exists(ref: str, root: Path) -> bool:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


def file_at_ref(ref: str, path: str, root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout


def changed_python_files(base: str, root: Path) -> list[str]:
    diff = git_text(
        ["diff", "--name-only", "--diff-filter=ACMR", base, "--", "*.py"],
        root,
    )
    others = git_text(["ls-files", "--others", "--exclude-standard"], root)
    names: list[str] = []
    for blob in (diff, others):
        for line in blob.splitlines():
            name = line.strip()
            if name.endswith(".py") and name not in names:
                names.append(name)
    return names


def change_counts(root: Path) -> dict[str, int]:
    text = git_text(["log", "--format=", "--name-only"], root)
    counts: dict[str, int] = {}
    for line in text.splitlines():
        name = line.strip()
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    return counts
