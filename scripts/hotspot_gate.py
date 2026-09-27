"""Fail when a changed Python file is both complex and frequently changed."""

from __future__ import annotations

import argparse
import sys

from hotspot import TOP_N, hotspot_failures
from ratchet_complexity import MAX_CCN, max_function_complexity
from ratchet_git import change_counts, changed_python_files, ref_exists, repo_root


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hotspot gate against a git base ref.")
    parser.add_argument("--base", default="origin/main")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = repo_root()
    if not ref_exists(args.base, root):
        print(f"missing base ref {args.base}", file=sys.stderr)
        return 2
    counts = change_counts(root)
    changed = changed_python_files(args.base, root)
    complexity = {
        path: max_function_complexity((root / path).read_text(encoding="utf-8"))
        for path in changed
    }
    failures, hot = hotspot_failures(
        changed,
        counts,
        complexity,
        top_n=TOP_N,
        max_ccn=MAX_CCN,
    )
    print(f"top change-frequency set (ties at rank {TOP_N} included):")
    ranked = sorted(hot, key=lambda name: (-counts[name], name))
    for name in ranked:
        print(f"  {counts[name]:4} {name}")
    if failures:
        print("hotspot failures:", file=sys.stderr)
        for path in failures:
            print(f"  {path} ccn={complexity[path]} changes={counts.get(path, 0)}", file=sys.stderr)
        return 1
    print(f"hotspot gate: pass (base {args.base})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
