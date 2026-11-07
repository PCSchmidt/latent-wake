#!/bin/bash
# detect-runtime.sh — best-effort detection of the AI coding platform/runtime.
#
# Prints exactly one platform id to stdout:
#   claude-code | cursor | windsurf | cline | generic
#
# HONEST SCOPE: only Claude Code exposes a reliable environment signal
# (CLAUDECODE / CLAUDE_CODE_*). Editors (Cursor/Windsurf/Cline) do not expose a
# dependable terminal env var — and several run *inside* VS Code, so VSCODE_*
# cannot distinguish them — so they are inferred from pre-existing project
# marker files. That is heuristic; when nothing matches, this prints 'generic'.
# Pass an explicit --platform to install.sh / gen-rules.sh when you want
# certainty rather than a guess.
#
# Usage:
#   detect-runtime.sh [project-dir]
#   MERIDIAN_PROJECT_DIR=/path detect-runtime.sh
#
# Exit codes: 0 always (detection never fails; worst case is 'generic').

set -uo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-${1:-$(pwd)}}"

# 1) Environment — reliable only for Claude Code. Checked first precisely
#    because Cline (and Claude Code itself) run inside VS Code, so a VSCODE_*
#    var must NOT be read as "an editor"; CLAUDECODE disambiguates.
if [ "${CLAUDECODE:-}" = "1" ] || [ -n "${CLAUDE_CODE_ENTRYPOINT:-}" ]; then
    echo "claude-code"
    exit 0
fi

# 2) Pre-existing project markers (heuristic — editors create these dirs).
if [ -d "$PROJECT_DIR/.cursor" ]; then
    echo "cursor"
    exit 0
fi
if [ -d "$PROJECT_DIR/.windsurf" ] || [ -f "$PROJECT_DIR/.windsurfrules" ]; then
    echo "windsurf"
    exit 0
fi
if [ -e "$PROJECT_DIR/.clinerules" ]; then
    echo "cline"
    exit 0
fi
if [ -d "$PROJECT_DIR/.claude" ]; then
    echo "claude-code"
    exit 0
fi

# 3) Nothing matched — honest default.
echo "generic"
exit 0
