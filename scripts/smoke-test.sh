#!/usr/bin/env bash
# Validate imports and MCP tool registration without requiring a real vault.
# A missing OBSIDIAN_VAULT_PATH uses a temporary fixture. A set path that is
# not a directory fails and is not created. Pytest still runs unless
# SMOKE_SKIP_PYTEST=1 (CI runs the suite in the pytest job).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

SMOKE_TEMP_VAULT=""
cleanup() {
  if [[ -n "$SMOKE_TEMP_VAULT" && -d "$SMOKE_TEMP_VAULT" ]]; then
    rm -rf "$SMOKE_TEMP_VAULT"
  fi
}
trap cleanup EXIT

if [[ -z "${OBSIDIAN_VAULT_PATH:-}" ]]; then
  SMOKE_TEMP_VAULT="$(mktemp -d)"
  export OBSIDIAN_VAULT_PATH="$SMOKE_TEMP_VAULT"
fi

if [[ ! -d "$OBSIDIAN_VAULT_PATH" ]]; then
  echo "Configured vault does not exist: $OBSIDIAN_VAULT_PATH" >&2
  exit 1
fi

if python -c "import obsidian_dev_memory" >/dev/null 2>&1; then
  RUNNER="python"
elif command -v uv >/dev/null 2>&1; then
  RUNNER="uv"
else
  echo "python with obsidian_dev_memory, or uv, is required" >&2
  exit 1
fi

run_python() {
  if [[ "$RUNNER" == "uv" ]]; then
    uv run python "$@"
  else
    python "$@"
  fi
}

echo "Vault: $OBSIDIAN_VAULT_PATH"
echo "Importing Python package..."
run_python -c "import obsidian_dev_memory; print(obsidian_dev_memory.__version__)"

echo "Checking MCP server tools..."
run_python "$SCRIPT_DIR/smoke_server.py"

if [[ "${SMOKE_SKIP_PYTEST:-}" == "1" ]]; then
  echo "Smoke test passed."
  exit 0
fi

echo "Running tests..."
if [[ "$RUNNER" == "uv" ]]; then
  uv run pytest
else
  python -m pytest
fi
echo "Smoke test passed."
