"""Fail when ruff reports a finding that is not in the committed baseline.

This command only reads the baseline. It does not rewrite it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from ratchet_git import repo_root

BASELINE_NAME = Path("config") / "ruff-baseline.json"
RUFF_PATHS = ["src", "tests", "scripts"]


def fingerprint(item: dict, root: Path) -> tuple[str, str, str]:
    filename = str(item.get("filename", ""))
    path = Path(filename)
    if path.is_absolute():
        try:
            filename = path.resolve().relative_to(root).as_posix()
        except ValueError:
            filename = path.as_posix()
    code = str(item.get("code", ""))
    message = str(item.get("message", ""))
    return filename, code, message


def findings_beyond_baseline(
    baseline: list[dict],
    current: list[dict],
    root: Path,
) -> list[tuple[tuple[str, str, str], int]]:
    base_counts = Counter(fingerprint(item, root) for item in baseline)
    current_counts = Counter(fingerprint(item, root) for item in current)
    extra: list[tuple[tuple[str, str, str], int]] = []
    for key, count in sorted(current_counts.items()):
        overflow = count - base_counts[key]
        if overflow > 0:
            extra.append((key, overflow))
    return extra


def collect_ruff_findings(root: Path) -> list[dict]:
    completed = subprocess.run(
        ["ruff", "check", *RUFF_PATHS, "--output-format", "json", "--no-cache"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode not in (0, 1):
        detail = completed.stderr.strip() or completed.stdout.strip() or "ruff failed"
        raise RuntimeError(detail)
    payload = completed.stdout.strip() or "[]"
    data = json.loads(payload)
    if not isinstance(data, list):
        raise RuntimeError("ruff JSON was not a list")
    return data


def main() -> int:
    root = repo_root()
    baseline_path = root / BASELINE_NAME
    if not baseline_path.is_file():
        print(f"missing ruff baseline {baseline_path}", file=sys.stderr)
        return 2
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if not isinstance(baseline, list):
        print("ruff baseline must be a JSON list", file=sys.stderr)
        return 2
    try:
        current = collect_ruff_findings(root)
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    extra = findings_beyond_baseline(baseline, current, root)
    print(f"ruff baseline findings: {len(baseline)}")
    print(f"ruff current findings: {len(current)}")
    if extra:
        print("new ruff findings:", file=sys.stderr)
        for key, overflow in extra:
            filename, code, message = key
            print(f"  {filename}: {code} x{overflow} {message}", file=sys.stderr)
        return 1
    print("ruff baseline gate: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
