#!/usr/bin/env python3
"""Fail when the smoke vault is missing or create_server drops tools."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

REQUIRED_TOOLS = (
    "get_project_context",
    "capture_work_session",
    "record_decision",
    "update_project_state",
    "search_memory",
    "read_note",
    "append_daily_note",
    "list_open_tasks",
    "list_blocked_tasks",
    "claim_task",
    "complete_task",
    "block_task",
    "unblock_task",
)


def missing_tool_names(names: list[str]) -> list[str]:
    present = set(names)
    return [name for name in REQUIRED_TOOLS if name not in present]


def evaluate_smoke(
    vault_path: str,
    *,
    server_factory: Callable[[Any], Any] | None = None,
) -> list[str]:
    """Return registered tool names, or exit when the vault or tools are unusable.

    A temporary fixture directory is enough. A missing path is not created.
    An empty or partial tool list fails even when that directory exists.
    """
    path = Path(vault_path)
    if not path.is_dir():
        raise SystemExit(f"Configured vault does not exist: {vault_path}")
    from obsidian_dev_memory.server import create_server, list_tool_names
    from obsidian_dev_memory.vault import Vault

    vault = Vault(path)
    factory = server_factory or create_server
    names = list_tool_names(factory(vault))
    missing = missing_tool_names(names)
    if missing:
        raise SystemExit("create_server dropped tools: " + ", ".join(missing))
    return names


def main() -> int:
    vault = os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
    if not vault:
        print("OBSIDIAN_VAULT_PATH is required", file=sys.stderr)
        return 1
    try:
        names = evaluate_smoke(vault)
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        print(exc.code or "smoke check failed", file=sys.stderr)
        return 1
    print("registered tools:", ", ".join(names))
    print("smoke tools ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
