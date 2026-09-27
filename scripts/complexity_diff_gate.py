"""Fail when a diff adds or worsens function complexity versus a base ref.

Functions already over the threshold are printed and do not fail the gate
unless this diff made them more complex.
"""

from __future__ import annotations

import argparse
import sys

from ratchet_complexity import MAX_CCN, classify_functions, function_complexities, legacy_report
from ratchet_git import changed_python_files, file_at_ref, ref_exists, repo_root


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean-as-you-code complexity gate against a git base ref.",
    )
    parser.add_argument("--base", default="origin/main")
    return parser.parse_args(argv)


def failures_against_base(base: str) -> list[str]:
    root = repo_root()
    failures: list[str] = []
    for path in changed_python_files(base, root):
        current_text = (root / path).read_text(encoding="utf-8")
        current = function_complexities(current_text)
        base_text = file_at_ref(base, path, root)
        previous = {} if base_text is None else function_complexities(base_text)
        file_failures, _legacy = classify_functions(previous, current, max_ccn=MAX_CCN)
        for item in file_failures:
            failures.append(f"{path}: {item}")
    return failures


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = repo_root()
    if not ref_exists(args.base, root):
        print(f"missing base ref {args.base}", file=sys.stderr)
        return 2
    print("legacy functions over threshold (visible, not failing):")
    for row in legacy_report(root, max_ccn=MAX_CCN):
        print(f"  {row}")
    failures = failures_against_base(args.base)
    if failures:
        print("complexity diff failures:", file=sys.stderr)
        for item in failures:
            print(f"  {item}", file=sys.stderr)
        return 1
    print(f"complexity diff gate: pass (base {args.base})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
