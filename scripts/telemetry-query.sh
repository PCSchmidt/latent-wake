#!/bin/bash
# telemetry-query.sh
# Meridian Telemetry Query Tool
#
# Reads and filters .meridian/telemetry.jsonl for human-readable reports.
# Used by /health report to surface stats and trends.
#
# Usage:
#   telemetry-query.sh summary              # Overall stats
#   telemetry-query.sh gates                # Gate pass/fail history
#   telemetry-query.sh tools [--top N]      # Most used tools
#   telemetry-query.sh errors               # Error events
#   telemetry-query.sh session <id>         # Events for a session
#   telemetry-query.sh tail [N]             # Last N events (default 20)

set -euo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-$(pwd)}"
TELEMETRY_FILE="$PROJECT_DIR/.meridian/telemetry.jsonl"

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

#######################################
# Check telemetry file exists and jq available
#######################################
check_deps() {
    if [ ! -f "$TELEMETRY_FILE" ]; then
        echo "No telemetry data found at $TELEMETRY_FILE"
        echo "Telemetry is written automatically during hook execution."
        return 1
    fi

    if ! command -v jq >/dev/null 2>&1; then
        echo "jq is required for telemetry queries. Install jq to use this command."
        return 1
    fi
    return 0
}

#######################################
# Read valid JSONL lines from telemetry file
# Handles both compact (one-per-line) and multi-line pretty-printed JSON
#######################################
read_telemetry() {
    # Normalize: collapse pretty-printed multi-line JSON into one line each
    jq -c '.' "$TELEMETRY_FILE" 2>/dev/null || true
}

#######################################
# Count events by type
#######################################
count_by_type() {
    read_telemetry | jq -r '.event_type' | sort | uniq -c | sort -rn
}

#######################################
# Summary view
#######################################
cmd_summary() {
    check_deps || return 0

    echo ""
    echo -e "${BLUE}━━━ Telemetry Summary ━━━${NC}"
    echo ""

    local all_events
    all_events=$(read_telemetry)

    local total
    total=$(echo "$all_events" | grep -c . 2>/dev/null || echo 0)
    echo "Total events:  $total"

    local first_event last_event
    first_event=$(echo "$all_events" | head -1 | jq -r '.timestamp // "unknown"')
    last_event=$(echo "$all_events" | tail -1 | jq -r '.timestamp // "unknown"')
    echo "First event:   $first_event"
    echo "Last event:    $last_event"

    echo ""
    echo "Events by type:"
    count_by_type | while read -r count type; do
        printf "  %-25s %s\n" "$type" "$count"
    done

    local gates_passed errors
    gates_passed=$(echo "$all_events" | jq -r 'select(.event_type=="gate_passed")' | jq -s 'length')
    errors=$(echo "$all_events" | jq -r 'select(.event_type=="error")' | jq -s 'length')

    echo ""
    echo -e "Gates passed:  ${GREEN}$gates_passed${NC}"
    if [ "$errors" -gt 0 ]; then
        echo -e "Errors logged: ${RED}$errors${NC}"
    else
        echo -e "Errors logged: ${GREEN}$errors${NC}"
    fi
}

#######################################
# Gate history
#######################################
cmd_gates() {
    check_deps || return 0

    echo ""
    echo -e "${BLUE}━━━ Gate History ━━━${NC}"
    echo ""

    local all_events
    all_events=$(read_telemetry)

    echo "$all_events" | jq -r 'select(.event_type == "gate_passed" or .event_type == "gate_blocked") |
        "\(.event_type) \(.timestamp) gate=\(.gate // "?") \(if .event_type == "gate_passed" then "predicted=\(.predicted_hours // "?")h actual=\(.actual_hours // "?")h" else "reason=\(.reason // "unknown")" end)"' \
        2>/dev/null | while read -r line; do
        if echo "$line" | grep -q "gate_passed"; then
            echo -e "  ${GREEN}✓${NC} ${line#gate_passed }"
        else
            echo -e "  ${RED}✗${NC} ${line#gate_blocked }"
        fi
    done

    # Summary
    local passed blocked
    passed=$(echo "$all_events" | jq -r 'select(.event_type=="gate_passed")' | jq -s 'length')
    blocked=$(echo "$all_events" | jq -r 'select(.event_type=="gate_blocked")' | jq -s 'length')
    echo ""
    echo "Passed: $passed  Blocked: $blocked"
}

#######################################
# Tool usage breakdown
#######################################
cmd_tools() {
    local top_n="${1:-10}"
    top_n="${top_n#--top}"
    top_n="${top_n# }"
    [ -z "$top_n" ] && top_n=10

    check_deps || return 0

    echo ""
    echo -e "${BLUE}━━━ Tool Usage (top $top_n) ━━━${NC}"
    echo ""

    read_telemetry | jq -r 'select(.event_type == "tool_used") | .tool' 2>/dev/null \
        | sort | uniq -c | sort -rn | head -"$top_n" \
        | while read -r count tool; do
            printf "  %-20s %s\n" "$tool" "$count"
        done
}

#######################################
# Error events
#######################################
cmd_errors() {
    check_deps || return 0

    echo ""
    echo -e "${BLUE}━━━ Error Events ━━━${NC}"
    echo ""

    local all_events
    all_events=$(read_telemetry)

    local count
    count=$(echo "$all_events" | jq -r 'select(.event_type == "error")' | jq -s 'length')

    if [ "$count" -eq 0 ]; then
        echo -e "${GREEN}No errors logged${NC}"
        return 0
    fi

    echo "$all_events" | jq -r 'select(.event_type == "error") | "\(.timestamp) [\(.error_code // "ERR")] \(.message)"' \
        2>/dev/null | while read -r line; do
        echo -e "  ${RED}!${NC} $line"
    done

    echo ""
    echo "Total errors: $count"
}

#######################################
# Session events
#######################################
cmd_session() {
    local session_id="${1:-}"

    if [ -z "$session_id" ]; then
        # Default to current session
        if [ -f "$PROJECT_DIR/.meridian/session.json" ] && command -v jq >/dev/null 2>&1; then
            session_id=$(jq -r '.session_id // ""' "$PROJECT_DIR/.meridian/session.json")
        fi
    fi

    if [ -z "$session_id" ]; then
        echo "Usage: telemetry-query.sh session <session-id>"
        return 1
    fi

    check_deps || return 0

    echo ""
    echo -e "${BLUE}━━━ Session: $session_id ━━━${NC}"
    echo ""

    read_telemetry | jq -r "select(.session_id == \"$session_id\") | \"\(.timestamp) \(.event_type) \(if .gate then \"gate=\(.gate)\" else \"\" end) \(if .tool then \"tool=\(.tool)\" else \"\" end)\"" \
        2>/dev/null | while read -r line; do
        echo "  $line"
    done
}

#######################################
# Tail recent events
#######################################
cmd_tail() {
    local n="${1:-20}"

    check_deps || return 0

    echo ""
    echo -e "${BLUE}━━━ Last $n Events ━━━${NC}"
    echo ""

    read_telemetry | tail -"$n" | jq -r '"\(.timestamp) \(.event_type) \(if .gate then "gate=\(.gate)" else "" end) \(if .tool then "tool=\(.tool)" else "" end)"' \
        2>/dev/null | while read -r line; do
        echo "  $line"
    done
}

#######################################
# Main
#######################################
main() {
    local command="${1:-summary}"
    shift || true

    case "$command" in
        summary)  cmd_summary ;;
        gates)    cmd_gates ;;
        tools)    cmd_tools "$@" ;;
        errors)   cmd_errors ;;
        session)  cmd_session "$@" ;;
        tail)     cmd_tail "$@" ;;
        *)
            echo "Usage: telemetry-query.sh <summary|gates|tools|errors|session|tail>"
            exit 1
            ;;
    esac
}

main "$@"
