#!/bin/bash
# validate-spec.sh
# Meridian gate-transition validator (Gate 2.2)
#
# Validates a project SPEC.md: must exist, be non-trivial, have a title and at
# least one structured section. A spec is the source of truth tests are written
# from, so an empty or stub spec must block the gate.
#
# Usage:
#   validate-spec.sh [path]      # default: $PROJECT_DIR/SPEC.md
#
# Config (env):
#   SPEC_MIN_LINES      minimum non-blank lines (default 10)
#   SPEC_MIN_SECTIONS   minimum number of `## ` sections (default 1)
#
# Exit codes: 0 = valid, 2 = invalid (block)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/hook-wrapper.sh"
HOOK_NAME="validate-spec"

TARGET="${1:-$PROJECT_DIR/SPEC.md}"
MIN_LINES="${SPEC_MIN_LINES:-10}"
MIN_SECTIONS="${SPEC_MIN_SECTIONS:-1}"

main() {
    if [ ! -f "$TARGET" ]; then
        block "SPEC.md not found at $TARGET - a specification is required to pass this gate"
    fi

    local lines
    lines=$(grep -cve '^[[:space:]]*$' "$TARGET" 2>/dev/null || true); lines=${lines:-0}
    if [ "$lines" -lt "$MIN_LINES" ]; then
        block "SPEC.md is too thin ($lines non-blank lines, need >= $MIN_LINES) - looks like a stub"
    fi

    if ! grep -qE '^#[[:space:]]+' "$TARGET"; then
        block "SPEC.md has no top-level (# ) title heading"
    fi

    local sections
    sections=$(grep -cE '^##[[:space:]]+' "$TARGET" 2>/dev/null || true); sections=${sections:-0}
    if [ "$sections" -lt "$MIN_SECTIONS" ]; then
        block "SPEC.md has $sections section(s) (## ), need >= $MIN_SECTIONS - spec is unstructured"
    fi

    info "SPEC.md valid ($lines lines, $sections sections)"
    timer_end
    exit 0
}

main "$@"
