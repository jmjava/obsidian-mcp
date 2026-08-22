#!/usr/bin/env python3
"""Merge one MCP server entry into an editor config without clobbering others."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

CURSOR_ROOT = "mcpServers"
VSCODE_ROOT = "servers"


def merge_server_config(
    dest: Path,
    *,
    flavor: str,
    server_name: str,
    server_config: dict[str, Any],
) -> str:
    root_key = CURSOR_ROOT if flavor == "cursor" else VSCODE_ROOT
    data: dict[str, Any]
    if dest.exists():
        raw = dest.read_text(encoding="utf-8").strip()
        if not raw:
            data = {}
        else:
            try:
                loaded = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise SystemExit(
                    f"Refusing to overwrite invalid JSON in {dest}: {exc}"
                ) from exc
            if not isinstance(loaded, dict):
                raise SystemExit(f"Refusing to overwrite non-object JSON in {dest}")
            data = loaded
    else:
        data = {}

    servers = data.get(root_key)
    if servers is None:
        servers = {}
        data[root_key] = servers
    elif not isinstance(servers, dict):
        raise SystemExit(f"{dest} has a non-object {root_key} value; refusing to merge")

    action = "updated" if server_name in servers else "added"
    servers[server_name] = server_config
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return action


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--flavor", required=True, choices=("cursor", "vscode"))
    parser.add_argument("--name", default="obsidian-dev-memory")
    parser.add_argument("--config-json", required=True)
    args = parser.parse_args()
    try:
        server_config = json.loads(args.config_json)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid --config-json: {exc}") from exc
    if not isinstance(server_config, dict):
        raise SystemExit("--config-json must be a JSON object")
    action = merge_server_config(
        args.file,
        flavor=args.flavor,
        server_name=args.name,
        server_config=server_config,
    )
    print(f"{action} {args.name} in {args.file}")


if __name__ == "__main__":
    main()
