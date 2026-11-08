#!/bin/bash
# validate-roadmap.sh
# Meridian gate-transition validator (Gate 2.2)
#
# Validates a project ROADMAP.md: must exist and actually track gates with
# status. Meridian dogfoods gate-based progress tracking; this validator
# guards that the roadmap stays a real status surface, not an empty outline.
#
# Usage:
#   validate-roadmap.sh [path]      # default: $PROJECT_DIR/ROADMAP.md
#
# Config (env):
#   ROADMAP_MIN_GATES   minimum gate entries required (default 1)
#
# Exit codes: 0 = valid, 2 = invalid (block)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/hook-wrapper.sh"
HOOK_NAME="validate-roadmap"

TARGET="${1:-$PROJECT_DIR/ROADMAP.md}"
MIN_GATES="${ROADMAP_MIN_GATES:-1}"

main() {
    if [ ! -f "$TARGET" ]; then
        block "ROADMAP.md not found at $TARGET - gate roadmap is required to pass this gate"
    fi

    if ! grep -qE '^#[[:space:]]+' "$TARGET"; then
        block "ROADMAP.md has no top-level (# ) title heading"
    fi

    # Gate entries: headings like "#### G2.2:" / "## Gate 3" / "### Gate: X"
    local gates
    gates=$(grep -cE '^#{2,6}[[:space:]]+(G[0-9]+(\.[0-9]+)?|Gate)' "$TARGET" 2>/dev/null || true); gates=${gates:-0}
    if [ "$gates" -lt "$MIN_GATES" ]; then
        block "ROADMAP.md has $gates gate entr(ies), need >= $MIN_GATES - no trackable gates"
    fi

    # Status surface: at least one status marker must appear
    if ! grep -qiE '(Status:|Complete|In Progress|Not Started|✅)' "$TARGET"; then
        block "ROADMAP.md has no status markers (Status:/Complete/In Progress/Not Started) - not a tracking surface"
    fi

    info "ROADMAP.md valid ($gates gate entries, status markers present)"
    timer_end
    exit 0
}

main "$@"
