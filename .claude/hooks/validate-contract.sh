#!/bin/bash
# validate-contract.sh
# Meridian gate-transition validator (Gate 2.2)
#
# Validates a project CONTRACT.md: the file must exist, be non-trivial, and
# contain the required sections. Designed to run as a `hooks.pre` entry on a
# human_approval gate (e.g. `confirmed`) so a project cannot clear scope
# confirmation without an actual contract.
#
# Usage:
#   validate-contract.sh [path]      # default: $PROJECT_DIR/CONTRACT.md
#
# Config (env):
#   CONTRACT_REQUIRED_SECTIONS   pipe-separated heading names that MUST be
#                                present (default "Purpose|Scope"). Matched
#                                case-insensitively against markdown headings.
#
# Exit codes:
#   0 = valid (allow gate transition)
#   2 = invalid (block gate transition)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/hook-wrapper.sh"
HOOK_NAME="validate-contract"

TARGET="${1:-$PROJECT_DIR/CONTRACT.md}"
REQUIRED="${CONTRACT_REQUIRED_SECTIONS:-Purpose|Scope}"
RECOMMENDED="${CONTRACT_RECOMMENDED_SECTIONS:-Out of Scope|Deployment}"
MIN_LINES="${CONTRACT_MIN_LINES:-8}"

# Returns 0 if a markdown heading matching the given name exists (case-insensitive)
has_section() {
    grep -qiE "^#{1,6}[[:space:]]+.*$1" "$TARGET"
}

main() {
    if [ ! -f "$TARGET" ]; then
        block "CONTRACT.md not found at $TARGET - scope contract is required to pass this gate"
    fi

    local lines
    lines=$(grep -cve '^[[:space:]]*$' "$TARGET" 2>/dev/null || true); lines=${lines:-0}
    if [ "$lines" -lt "$MIN_LINES" ]; then
        block "CONTRACT.md is too thin ($lines non-blank lines, need >= $MIN_LINES) - looks like a stub"
    fi

    if ! grep -qE '^#[[:space:]]+' "$TARGET"; then
        block "CONTRACT.md has no top-level (# ) title heading"
    fi

    # Required sections (deterministic -> block)
    local missing="" sec
    local IFS='|'
    for sec in $REQUIRED; do
        has_section "$sec" || missing="${missing:+$missing, }$sec"
    done
    unset IFS
    if [ -n "$missing" ]; then
        block "CONTRACT.md missing required section(s): $missing"
    fi

    # Recommended sections (advisory -> warn)
    IFS='|'
    for sec in $RECOMMENDED; do
        has_section "$sec" || warn "CONTRACT.md missing recommended section: $sec"
    done
    unset IFS

    info "CONTRACT.md valid ($lines lines, required sections present)"
    timer_end
    exit 0
}

main "$@"
