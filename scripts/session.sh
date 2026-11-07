#!/bin/bash
# session.sh
# Meridian Session Manager
#
# Manages the .meridian/session.json file that tracks active session state.
# Called at session start/end to provide context for telemetry and hooks.
#
# Usage:
#   session.sh start [project=<name>]
#   session.sh end
#   session.sh id       # Print current session ID
#   session.sh status   # Print session status

set -euo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-$(pwd)}"
SESSION_FILE="$PROJECT_DIR/.meridian/session.json"
LOG_EVENT="$(dirname "${BASH_SOURCE[0]}")/log-event.sh"
LOG_EPISODIC="$(dirname "${BASH_SOURCE[0]}")/log-episodic.sh"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

#######################################
# Generate 8-char hex session ID from timestamp
#######################################
generate_session_id() {
    printf '%08x' "$(date +%s)"
}

#######################################
# Start a new session
#######################################
start_session() {
    local project="${1:-}"
    project="${project#project=}"

    # Default to directory name if not specified
    if [ -z "$project" ]; then
        project=$(basename "$PROJECT_DIR")
    fi

    local session_id
    session_id=$(generate_session_id)

    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%S")

    # Get current gate
    local current_gate="unknown"
    if [ -f "$PROJECT_DIR/scripts/gate-engine.sh" ]; then
        current_gate=$("$PROJECT_DIR/scripts/gate-engine.sh" current 2>/dev/null || echo "unknown")
    fi

    mkdir -p "$(dirname "$SESSION_FILE")"

    # Write session file
    cat > "$SESSION_FILE" << EOF
{
  "session_id": "$session_id",
  "project": "$project",
  "started": "$timestamp",
  "current_gate": "$current_gate",
  "tools_used": 0,
  "gates_passed": 0,
  "errors": 0
}
EOF

    echo -e "${GREEN}Session started:${NC} $session_id (project: $project)"

    # Log telemetry
    if [ -f "$LOG_EVENT" ]; then
        MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$LOG_EVENT" session_start \
            "current_gate=$current_gate" 2>/dev/null || true
    fi

    # Episodic memory
    if [ -f "$LOG_EPISODIC" ]; then
        MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$LOG_EPISODIC" session_start \
            --notes "gate:$current_gate" 2>/dev/null || true
    fi
}

#######################################
# End the current session
#######################################
end_session() {
    if [ ! -f "$SESSION_FILE" ]; then
        echo "No active session found" >&2
        return 1
    fi

    local session_id="unknown"
    local tools_used=0
    local gates_passed=0
    local errors=0

    if command -v jq >/dev/null 2>&1; then
        session_id=$(jq -r '.session_id' "$SESSION_FILE")
        tools_used=$(jq -r '.tools_used // 0' "$SESSION_FILE")
        gates_passed=$(jq -r '.gates_passed // 0' "$SESSION_FILE")
        errors=$(jq -r '.errors // 0' "$SESSION_FILE")
    fi

    # Log telemetry
    if [ -f "$LOG_EVENT" ]; then
        MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$LOG_EVENT" session_end \
            "tools_used=$tools_used" \
            "gates_passed=$gates_passed" \
            "errors=$errors" 2>/dev/null || true
    fi

    # Episodic memory
    if [ -f "$LOG_EPISODIC" ]; then
        MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$LOG_EPISODIC" session_end \
            --notes "tools:$tools_used gates:$gates_passed errors:$errors" 2>/dev/null || true
    fi

    echo -e "${GREEN}Session ended:${NC} $session_id"
    echo "  Tools used:   $tools_used"
    echo "  Gates passed: $gates_passed"
    echo "  Errors:       $errors"
}

#######################################
# Print current session ID
#######################################
print_id() {
    if [ ! -f "$SESSION_FILE" ]; then
        echo "no-session"
        return 0
    fi

    if command -v jq >/dev/null 2>&1; then
        jq -r '.session_id // "no-session"' "$SESSION_FILE"
    else
        grep '"session_id"' "$SESSION_FILE" | head -1 | sed 's/.*: *"\([^"]*\)".*/\1/'
    fi
}

#######################################
# Print session status
#######################################
print_status() {
    if [ ! -f "$SESSION_FILE" ]; then
        echo "No active session"
        return 0
    fi

    if command -v jq >/dev/null 2>&1; then
        jq '.' "$SESSION_FILE"
    else
        cat "$SESSION_FILE"
    fi
}

#######################################
# Increment a counter in session file
# Arguments:
#   $1 - field name (tools_used, gates_passed, errors)
#######################################
increment() {
    local field="$1"

    if [ ! -f "$SESSION_FILE" ] || ! command -v jq >/dev/null 2>&1; then
        return 0
    fi

    local temp_file
    temp_file=$(mktemp)
    jq ".$field = (.$field // 0) + 1" "$SESSION_FILE" > "$temp_file"
    mv "$temp_file" "$SESSION_FILE"
}

#######################################
# Main
#######################################
main() {
    local command="${1:-status}"

    case "$command" in
        start)
            shift
            start_session "$@"
            ;;
        end)
            end_session
            ;;
        id)
            print_id
            ;;
        status)
            print_status
            ;;
        increment)
            if [ $# -lt 2 ]; then
                echo "Usage: session.sh increment <field>" >&2
                exit 1
            fi
            increment "$2"
            ;;
        *)
            echo "Usage: session.sh <start|end|id|status|increment>"
            exit 1
            ;;
    esac
}

main "$@"
