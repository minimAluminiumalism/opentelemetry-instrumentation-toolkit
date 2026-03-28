#!/bin/bash
# Install OTel GenAI Instrumentation skill for all supported coding agents.
#
# Creates symlinks from each agent's discovery directory to the single
# source of truth under skills/.
#
# Supported agents:
#   - Claude Code  (.claude/skills/)
#   - Codex CLI    (.agents/skills/)
#   - OpenCode     (.opencode/skills/)
#
# Usage:
#   ./install.sh          # install for current project
#   ./install.sh --global # install to user-level directories

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_NAME="otel-genai-instrumentation"
SKILL_SOURCE="$SCRIPT_DIR/skills/$SKILL_NAME"

if [ ! -d "$SKILL_SOURCE" ]; then
    echo "Error: skill source not found at $SKILL_SOURCE" >&2
    exit 1
fi

if [ "${1:-}" = "--global" ]; then
    # User-level installation
    TARGETS=(
        "$HOME/.claude/skills"
        "$HOME/.agents/skills"
        "$HOME/.config/opencode/skills"
    )
    echo "Installing globally for current user..."
else
    # Project-level installation
    TARGETS=(
        "$SCRIPT_DIR/.claude/skills"
        "$SCRIPT_DIR/.agents/skills"
        "$SCRIPT_DIR/.opencode/skills"
    )
    echo "Installing for current project..."
fi

for target_dir in "${TARGETS[@]}"; do
    mkdir -p "$target_dir"
    link_path="$target_dir/$SKILL_NAME"

    # Remove existing link/dir if present
    if [ -L "$link_path" ] || [ -e "$link_path" ]; then
        rm -rf "$link_path"
    fi

    # Compute relative path from target to source
    # Use Python for reliable cross-platform relative path
    rel_path=$(python3 -c "
import os.path
print(os.path.relpath('$SKILL_SOURCE', '$target_dir'))
")

    ln -s "$rel_path" "$link_path"
    echo "  Linked: $link_path -> $rel_path"
done

echo ""
echo "Done. Skill '$SKILL_NAME' is now available in:"
echo "  - Claude Code  (implicit or /otel-genai-instrumentation)"
echo "  - Codex CLI    (implicit or \$otel-genai-instrumentation)"
echo "  - OpenCode     (skill_use otel_genai_instrumentation)"
