#!/bin/bash
# log-event.sh
# Meridian Telemetry Event Logger
#
# Appends a structured JSON event to .meridian/telemetry.jsonl
# Called by hooks, scripts, and gate engine to record all significant events.
#
# Usage:
#   log-event.sh <event_type> [key=value ...]
#
# Examples:
#   log-event.sh gate_passed gate=1.4 predicted_hours=6 actual_hours=5
#   log-event.sh gate_blocked gate=1.4 reason="dependency 1.3 not met"
#   log-event.sh tool_used tool=Edit hook=PostToolUse outcome=allowed
#   log-event.sh error message="validation failed" recoverable=true

set -euo pipefail

# Configuration
PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-$(pwd)}"
TELEMETRY_FILE="$PROJECT_DIR/.meridian/telemetry.jsonl"
SESSION_FILE="$PROJECT_DIR/.meridian/session.json"

# Colors
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

#######################################
# Get or create session ID
#
# Events logged outside a Claude Code session (the pre-commit verifier,
# Tier 2/3 editors, manual script runs) never see SessionStart, and the
# installed session.json has no session_id. Rather than stamp every such
# event "00000000", lazily create an id and persist it so later events
# group into the same session until session.sh starts a new one.
#######################################
get_session_id() {
    if ! command -v jq >/dev/null 2>&1; then
        printf '%08x' "$(date +%s)"
        return 0
    fi

    local sid=""
    if [ -f "$SESSION_FILE" ]; then
        sid=$(jq -r '.session_id // empty' "$SESSION_FILE" 2>/dev/null || true)
    fi
    if [[ "$sid" =~ ^[a-f0-9]{8}$ ]] && [ "$sid" != "00000000" ]; then
        echo "$sid"
        return 0
    fi

    sid=$(printf '%08x' "$(date +%s)")
    local started
    started=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%S")
    mkdir -p "$(dirname "$SESSION_FILE")"
    local base='{}'
    if [ -f "$SESSION_FILE" ] && jq empty "$SESSION_FILE" >/dev/null 2>&1; then
        base=$(cat "$SESSION_FILE")
    fi
    echo "$base" | jq --arg sid "$sid" --arg started "$started" --arg project "$(basename "$PROJECT_DIR")" \
        '.session_id = $sid | .started = (.started // $started) | .project = (.project // $project) | .auto_started = true' \
        > "$SESSION_FILE.tmp" 2>/dev/null && mv "$SESSION_FILE.tmp" "$SESSION_FILE" || rm -f "$SESSION_FILE.tmp"
    echo "$sid"
}

#######################################
# Escape a string for inclusion in a JSON string literal
#######################################
json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\t'/\\t}"
    # Drop any remaining control characters (invalid unescaped in JSON)
    printf '%s' "$s" | tr -d '\000-\010\013\014\016-\037'
}

#######################################
# Get project name
#######################################
get_project() {
    if [ -f "$SESSION_FILE" ] && command -v jq >/dev/null 2>&1; then
        jq -r '.project // "unknown"' "$SESSION_FILE" 2>/dev/null || basename "$PROJECT_DIR"
    else
        basename "$PROJECT_DIR"
    fi
}

#######################################
# Parse key=value arguments into JSON fields
# Arguments: key=value pairs
# Returns: JSON fragment (no outer braces)
#######################################
parse_kvs() {
    local json_fields=""

    for arg in "$@"; do
        local key="${arg%%=*}"
        local value="${arg#*=}"

        # Skip if no = found
        if [ "$key" = "$arg" ]; then
            continue
        fi

        # Determine value type
        if [[ "$value" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
            # Numeric
            json_fields="${json_fields}, \"$key\": $value"
        elif [ "$value" = "true" ] || [ "$value" = "false" ]; then
            # Boolean
            json_fields="${json_fields}, \"$key\": $value"
        elif [[ "$value" == "["* ]] && echo "$value" | jq -e 'type == "array"' >/dev/null 2>&1; then
            # Already a JSON array - pass through
            json_fields="${json_fields}, \"$key\": $value"
        else
            local escaped
            escaped=$(json_escape "$value")
            json_fields="${json_fields}, \"$key\": \"$escaped\""
        fi
    done

    echo "$json_fields"
}

#######################################
# Main
#######################################
main() {
    if [ $# -lt 1 ]; then
        echo "Usage: log-event.sh <event_type> [key=value ...]"
        echo ""
        echo "Event types:"
        echo "  gate_passed      gate=<id> predicted_hours=<n> actual_hours=<n>"
        echo "  gate_blocked     gate=<id> reason=<text> blocking_dep=<id>"
        echo "  tool_used        tool=<name> hook=<PreToolUse|PostToolUse> outcome=<allowed|blocked>"
        echo "  evaluator_verdict gate=<id> score=<0-10> verdict=<pass|fail|warn>"
        echo "  memory_write     memory_type=<type> validation=<pass|fail>"
        echo "  session_start    current_gate=<id>"
        echo "  session_end      tools_used=<n> gates_passed=<n> errors=<n>"
        echo "  error            message=<text> recoverable=<true|false>"
        exit 1
    fi

    local event_type="$1"
    shift

    # Ensure telemetry directory exists
    mkdir -p "$(dirname "$TELEMETRY_FILE")"

    # Build base event
    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%S")

    local session_id
    session_id=$(get_session_id)

    local project
    project=$(get_project)

    # Parse additional key=value pairs
    local extra_fields
    extra_fields=$(parse_kvs "$@")

    # Build JSON event
    local event
    event=$(printf '{"timestamp":"%s","event_type":"%s","session_id":"%s","project":"%s"%s}' \
        "$timestamp" \
        "$event_type" \
        "$session_id" \
        "$project" \
        "$extra_fields")

    # Validate JSON if jq available
    if command -v jq >/dev/null 2>&1; then
        if ! echo "$event" | jq empty 2>/dev/null; then
            echo -e "${RED}ERROR:${NC} Invalid JSON generated for telemetry event" >&2
            echo "Event: $event" >&2
            exit 1
        fi
    fi

    # Append to telemetry file
    echo "$event" >> "$TELEMETRY_FILE"

    # Confirm (only in verbose mode)
    if [ "${MERIDIAN_VERBOSE:-0}" = "1" ]; then
        echo -e "Telemetry: $event_type logged"
    fi
}

main "$@"
