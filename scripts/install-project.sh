#!/usr/bin/env bash
# Install Obsidian developer-memory MCP config into a target project.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/install-project.sh --project PATH --vault PATH [--server PATH]

Creates or updates:
  <project>/.cursor/mcp.json
  <project>/.cursor/rules/obsidian-memory.mdc
  <project>/.vscode/mcp.json
  <project>/.github/copilot-instructions.md
  <project>/.mcp.json
  <project>/.claude/rules/obsidian-memory.md

Existing unrelated MCP servers are preserved. Machine-specific paths are written
only into the target project, not into this repository.
EOF
}

PROJECT=""
VAULT=""
SERVER=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      PROJECT="${2:-}"
      shift 2
      ;;
    --vault)
      VAULT="${2:-}"
      shift 2
      ;;
    --server)
      SERVER="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$PROJECT" || -z "$VAULT" ]]; then
  usage >&2
  exit 1
fi

if [[ ! -d "$PROJECT" ]]; then
  echo "Target project does not exist: $PROJECT" >&2
  exit 1
fi

if [[ ! -d "$VAULT" ]]; then
  echo "Obsidian vault does not exist: $VAULT" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER_ROOT="${SERVER:-$REPO_ROOT}"

if [[ ! -d "$SERVER_ROOT/src/obsidian_dev_memory" ]]; then
  echo "MCP server repository not found: $SERVER_ROOT" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to merge MCP JSON safely." >&2
  exit 1
fi

PROJECT="$(cd "$PROJECT" && pwd)"
VAULT="$(cd "$VAULT" && pwd)"
SERVER_ROOT="$(cd "$SERVER_ROOT" && pwd)"

SERVER_JSON="$(
  SERVER_ROOT="$SERVER_ROOT" VAULT="$VAULT" python3 - <<'PY'
import json
import os

print(json.dumps({
    "type": "stdio",
    "command": "uv",
    "args": [
        "--directory",
        os.environ["SERVER_ROOT"],
        "run",
        "python",
        "-m",
        "obsidian_dev_memory",
    ],
    "env": {
        "OBSIDIAN_VAULT_PATH": os.environ["VAULT"],
        "OBSIDIAN_MEMORY_ROOT": "AI Memory",
    },
}))
PY
)"

echo "Installing obsidian-dev-memory into $PROJECT"
echo "  MCP server: $SERVER_ROOT"
echo "  Vault:      $VAULT"

python3 "$SCRIPT_DIR/merge_mcp_config.py" \
  --file "$PROJECT/.cursor/mcp.json" \
  --flavor cursor \
  --config-json "$SERVER_JSON"

python3 "$SCRIPT_DIR/merge_mcp_config.py" \
  --file "$PROJECT/.vscode/mcp.json" \
  --flavor vscode \
  --config-json "$SERVER_JSON"

python3 "$SCRIPT_DIR/merge_mcp_config.py" \
  --file "$PROJECT/.mcp.json" \
  --flavor claude \
  --config-json "$SERVER_JSON"

RULE_SRC="$REPO_ROOT/.cursor/rules/obsidian-memory.mdc"
RULE_DEST="$PROJECT/.cursor/rules/obsidian-memory.mdc"
mkdir -p "$(dirname "$RULE_DEST")"
cp "$RULE_SRC" "$RULE_DEST"
echo "wrote $RULE_DEST"

COPILOT_SRC="$REPO_ROOT/.github/copilot-instructions.md"
COPILOT_DEST="$PROJECT/.github/copilot-instructions.md"
mkdir -p "$(dirname "$COPILOT_DEST")"
cp "$COPILOT_SRC" "$COPILOT_DEST"
echo "wrote $COPILOT_DEST"

CLAUDE_RULE_SRC="$REPO_ROOT/.claude/rules/obsidian-memory.md"
CLAUDE_RULE_DEST="$PROJECT/.claude/rules/obsidian-memory.md"
mkdir -p "$(dirname "$CLAUDE_RULE_DEST")"
cp "$CLAUDE_RULE_SRC" "$CLAUDE_RULE_DEST"
echo "wrote $CLAUDE_RULE_DEST"

cat <<EOF

Installed files:
  $PROJECT/.cursor/mcp.json
  $PROJECT/.cursor/rules/obsidian-memory.mdc
  $PROJECT/.vscode/mcp.json
  $PROJECT/.github/copilot-instructions.md
  $PROJECT/.mcp.json
  $PROJECT/.claude/rules/obsidian-memory.md

Follow-up:
  1. Confirm uv is on PATH in Cursor, VS Code, and Claude Code.
  2. Reload the window or restart MCP servers so tools are discovered.
     Claude Code may ask you to approve the project server on first use.
  3. Expected tools:
       get_project_context
       capture_work_session
       record_decision
       update_project_state
       search_memory
       read_note
       append_daily_note
  4. Optional vault override:
       export OBSIDIAN_MEMORY_ROOT="Engineering Memory"
EOF
