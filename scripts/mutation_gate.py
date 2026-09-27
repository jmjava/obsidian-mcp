"""Run mutmut on markdown.py and fail if survivors increase.

Reads config/mutmut-baseline.json. Does not rewrite that file.
Prints the stats mutmut actually produced. Does not invent a score.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

from ratchet_git import repo_root

BASELINE_NAME = "config/mutmut-baseline.json"
STATS_NAME = "mutants/mutmut-cicd-stats.json"


def mutation_regression(baseline: dict, current: dict) -> list[str]:
    reasons: list[str] = []
    total = int(current.get("total", 0))
    if total <= 0:
        reasons.append("mutmut reported no mutants")
    survived = int(current.get("survived", 0))
    if survived > int(baseline.get("survived", 0)):
        reasons.append(f"survived increased {baseline.get('survived')} -> {survived}")
    return reasons


def _run(command: list[str], root) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=root,
        text=True,
        check=False,
    )


def main() -> int:
    if shutil.which("mutmut") is None:
        print("mutmut is not installed; mutation score was not computed", file=sys.stderr)
        return 2
    root = repo_root()
    baseline_path = root / BASELINE_NAME
    if not baseline_path.is_file():
        print(f"missing mutation baseline {baseline_path}", file=sys.stderr)
        return 2
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    run = _run(["mutmut", "run"], root)
    if run.returncode != 0:
        print(f"mutmut run exited {run.returncode}", file=sys.stderr)
        return run.returncode
    exported = _run(["mutmut", "export-cicd-stats"], root)
    if exported.returncode != 0:
        print(f"mutmut export-cicd-stats exited {exported.returncode}", file=sys.stderr)
        return exported.returncode
    stats_path = root / STATS_NAME
    if not stats_path.is_file():
        print("mutmut did not write cicd stats", file=sys.stderr)
        return 2
    current = json.loads(stats_path.read_text(encoding="utf-8"))
    print(json.dumps(current, indent=2, sort_keys=True))
    reasons = mutation_regression(baseline, current)
    if reasons:
        print("mutation regression:", file=sys.stderr)
        for reason in reasons:
            print(f"  {reason}", file=sys.stderr)
        return 1
    print("mutation gate: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
