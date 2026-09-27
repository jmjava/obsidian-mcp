"""Change-frequency hotspot set."""

from __future__ import annotations

TOP_N = 10


def top_change_set(counts: dict[str, int], top_n: int = TOP_N) -> set[str]:
    if not counts or top_n <= 0:
        return set()
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    cutoff = ranked[min(top_n, len(ranked)) - 1][1]
    return {name for name, count in ranked if count >= cutoff}


def hotspot_failures(
    changed: list[str],
    counts: dict[str, int],
    complexity_by_file: dict[str, int],
    *,
    top_n: int = TOP_N,
    max_ccn: int = 10,
) -> tuple[list[str], set[str]]:
    """Fail only when a changed Python file is both complex and frequent."""
    hot = top_change_set(counts, top_n)
    failures: list[str] = []
    for path in changed:
        if not path.endswith(".py"):
            continue
        if path not in hot:
            continue
        if complexity_by_file.get(path, 1) > max_ccn:
            failures.append(path)
    return failures, hot
