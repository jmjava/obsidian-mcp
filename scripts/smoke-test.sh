#!/usr/bin/env bash
# Validate local environment, imports, and the test suite.
set -euo pipefail

if [[ -z "${OBSIDIAN_VAULT_PATH:-}" ]]; then
  echo "OBSIDIAN_VAULT_PATH is required" >&2
  echo "Example: export OBSIDIAN_VAULT_PATH=\"\$HOME/Documents/ObsidianVault\"" >&2
  exit 1
fi

if [[ ! -d "$OBSIDIAN_VAULT_PATH" ]]; then
  echo "Configured vault does not exist: $OBSIDIAN_VAULT_PATH" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it from https://docs.astral.sh/uv/" >&2
  exit 1
fi

echo "Vault: $OBSIDIAN_VAULT_PATH"
echo "Importing Python package..."
uv run python -c "import obsidian_dev_memory; print(obsidian_dev_memory.__version__)"

echo "Importing MCP server module..."
uv run python - <<'PY'
from obsidian_dev_memory.server import create_server, list_tool_names
from obsidian_dev_memory.vault import Vault

vault = Vault.from_env()
server = create_server(vault)
names = list_tool_names(server)
print("registered tools:", ", ".join(names) if names else "(discovered at runtime)")
print("server import and construction succeeded")
PY

echo "Running tests..."
uv run pytest
echo "Smoke test passed."
