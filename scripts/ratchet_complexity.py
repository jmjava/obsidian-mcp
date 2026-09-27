"""Cyclomatic complexity for the clean-as-you-code and hotspot gates.

Decision points follow McCabe: if, loops, except, with, boolean operators,
comprehensions, and match cases. Assert statements are not counted.
"""

from __future__ import annotations

import ast
from pathlib import Path

MAX_CCN = 10

_BRANCH_TYPES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
    ast.IfExp,
)
_COMP_TYPES = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_SKIP_NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def branch_weight(node: ast.AST) -> int:
    if isinstance(node, _BRANCH_TYPES):
        return 1
    if isinstance(node, ast.BoolOp):
        return max(0, len(node.values) - 1)
    if isinstance(node, ast.Match):
        return len(node.cases)
    if isinstance(node, _COMP_TYPES):
        return 1 + sum(len(generator.ifs) for generator in node.generators)
    return 0


def cyclomatic_complexity(function: ast.AST) -> int:
    score = 1
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        if isinstance(node, _SKIP_NESTED):
            continue
        score += branch_weight(node)
        stack.extend(ast.iter_child_nodes(node))
    return score


def _store(found: dict[str, int], name: str, score: int) -> None:
    key = name
    index = 2
    while key in found:
        key = f"{name}#{index}"
        index += 1
    found[key] = score


def function_complexities(source: str) -> dict[str, int]:
    tree = ast.parse(source)
    found: dict[str, int] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}{child.name}"
                _store(found, qualname, cyclomatic_complexity(child))
                walk(child, f"{qualname}.")
            else:
                walk(child, prefix)

    walk(tree, "")
    return found


def classify_functions(
    base: dict[str, int],
    current: dict[str, int],
    *,
    max_ccn: int = MAX_CCN,
) -> tuple[list[str], list[str]]:
    """Return (failures, legacy notes).

    Failures are new functions over the threshold or any complexity increase.
    Existing functions over the threshold stay in the legacy notes.
    """
    failures: list[str] = []
    legacy: list[str] = []
    for name in sorted(current):
        score = current[name]
        if name not in base:
            if score > max_ccn:
                failures.append(f"new {name} ccn={score}")
            continue
        previous = base[name]
        if score > previous:
            failures.append(f"worsened {name} {previous}->{score}")
            continue
        if score > max_ccn:
            legacy.append(f"legacy {name} ccn={score}")
    return failures, legacy


def max_function_complexity(source: str) -> int:
    scores = function_complexities(source)
    if not scores:
        return 1
    return max(scores.values())


def python_sources(root: Path) -> list[Path]:
    found: list[Path] = []
    for folder in ("src", "tests", "scripts"):
        base = root / folder
        if not base.is_dir():
            continue
        found.extend(sorted(base.rglob("*.py")))
    return found


def legacy_report(root: Path, *, max_ccn: int = MAX_CCN) -> list[str]:
    rows: list[str] = []
    for path in python_sources(root):
        scores = function_complexities(path.read_text(encoding="utf-8"))
        relative = path.relative_to(root).as_posix()
        for name, score in sorted(scores.items()):
            if score > max_ccn:
                rows.append(f"{relative}:{name} ccn={score}")
    return rows
