#!/bin/bash
# SessionStart.sh
# Meridian SessionStart Hook
#
# Fires at the start of each Claude Code conversation.
# Auto-starts a Meridian session so session.json always has a valid session_id.
# This fixes F3 from MERIDIAN_DOGFOOD.md: session.sh start was never auto-called,
# leaving session.json with session_id "00000000" for the entire session.
#
# Exit codes: 0 always (session start is best-effort, never blocks a session)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/hook-wrapper.sh"

HOOK_NAME="SessionStart"

main() {
    info "SessionStart hook fired"

    local session_script="$PROJECT_DIR/scripts/session.sh"

    if [ ! -f "$session_script" ]; then
        info "session.sh not found — not a Meridian project, skipping"
        timer_end
        exit 0
    fi

    if ! check_meridian_project; then
        info "Not a Meridian project — skipping session auto-start"
        timer_end
        exit 0
    fi

    MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$session_script" start 2>/dev/null || true
    info "Session auto-started"

    timer_end
    exit 0
}

main "$@"
