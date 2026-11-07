#!/bin/bash
# status-report.sh
# Meridian Status Report
#
# Compact session-start report answering "where am I in this project?"
# Reads corrections.jsonl (completed gates), session.json, and telemetry.
#
# Usage:
#   status-report.sh              # Full status (default)
#   status-report.sh --json       # Machine-readable JSON output
#   status-report.sh --short      # One-line summary

set -euo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-$(pwd)}"
MERIDIAN_DIR="$PROJECT_DIR/.meridian"
SESSION_FILE="$MERIDIAN_DIR/session.json"
CORRECTIONS_FILE="$MERIDIAN_DIR/memory/corrections.jsonl"
TELEMETRY_FILE="$MERIDIAN_DIR/telemetry.jsonl"

FEATURES_FILE="$MERIDIAN_DIR/FEATURES.json"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

# ─── Helpers ──────────────────────────────────────────────────────────────────

check_jq() {
    if ! command -v jq >/dev/null 2>&1; then
        echo "Error: jq is required. Install with: apt-get install jq / brew install jq" >&2
        exit 1
    fi
}

read_telemetry() {
    if [ -f "$TELEMETRY_FILE" ]; then
        jq -c '.' "$TELEMETRY_FILE" 2>/dev/null || true
    fi
}

# ─── Gather state ─────────────────────────────────────────────────────────────

get_current_gate() {
    if [ -f "$SESSION_FILE" ] && command -v jq >/dev/null 2>&1; then
        jq -r '.current_gate // "unknown"' "$SESSION_FILE" 2>/dev/null || echo "unknown"
    else
        echo "unknown"
    fi
}

get_completed_gates() {
    if [ ! -f "$CORRECTIONS_FILE" ]; then
        echo ""
        return
    fi
    # Returns one gate ID per line, in file order
    jq -r '.gate // empty' "$CORRECTIONS_FILE" 2>/dev/null || true
}

get_gate_count() {
    if [ ! -f "$CORRECTIONS_FILE" ]; then
        echo 0
        return
    fi
    wc -l < "$CORRECTIONS_FILE" | tr -d ' '
}

get_avg_calibration() {
    if [ ! -f "$CORRECTIONS_FILE" ] || [ "$(get_gate_count)" -eq 0 ]; then
        echo "n/a"
        return
    fi
    jq -s '[.[].delta_ratio] | add / length | . * 100 | round / 100' \
        "$CORRECTIONS_FILE" 2>/dev/null | awk '{printf "%.2f", $1}' || echo "n/a"
}

# Returns lifecycle summary inline: "90% happy-path / 50% full-lifecycle (10 features)"
# Returns empty string when FEATURES.json does not exist.
get_lifecycle_summary() {
    [ -f "$FEATURES_FILE" ] || return 0

    local stats total happy full happy_pct full_pct
    stats=$(jq -c '{
        total:          length,
        happy_path:     [.[] | select(.lifecycle.happy_path     == true)] | length,
        full_lifecycle: [.[] | select(
            .lifecycle.happy_path     == true and
            .lifecycle.integration    == true and
            .lifecycle.edge_cases     == true and
            .lifecycle.error_handling == true and
            .lifecycle.hardening      == true
        )] | length
    }' "$FEATURES_FILE" 2>/dev/null | tr -d '\r') || return 0

    total=$(echo "$stats" | jq '.total'          | tr -d '\r')
    happy=$(echo "$stats" | jq '.happy_path'     | tr -d '\r')
    full=$( echo "$stats" | jq '.full_lifecycle' | tr -d '\r')

    [ "$total" -eq 0 ] && return 0

    happy_pct=$(awk "BEGIN {printf \"%d\", $happy * 100 / $total}")
    full_pct=$( awk "BEGIN {printf \"%d\", $full  * 100 / $total}")

    echo "${happy_pct}% happy-path / ${full_pct}% full-lifecycle  (${total} features)"
}

get_lifecycle_json() {
    [ -f "$FEATURES_FILE" ] || { echo "null"; return 0; }

    local stats total happy full happy_pct full_pct
    stats=$(jq -c '{
        total:          length,
        happy_path:     [.[] | select(.lifecycle.happy_path     == true)] | length,
        integration:    [.[] | select(.lifecycle.integration    == true)] | length,
        edge_cases:     [.[] | select(.lifecycle.edge_cases     == true)] | length,
        error_handling: [.[] | select(.lifecycle.error_handling == true)] | length,
        hardening:      [.[] | select(.lifecycle.hardening      == true)] | length,
        full_lifecycle: [.[] | select(
            .lifecycle.happy_path     == true and
            .lifecycle.integration    == true and
            .lifecycle.edge_cases     == true and
            .lifecycle.error_handling == true and
            .lifecycle.hardening      == true
        )] | length
    }' "$FEATURES_FILE" 2>/dev/null | tr -d '\r') || { echo "null"; return 0; }

    total=$(echo "$stats" | jq '.total'          | tr -d '\r')
    [ "$total" -eq 0 ] && { echo "null"; return 0; }

    happy=$(echo "$stats" | jq '.happy_path'     | tr -d '\r')
    full=$( echo "$stats" | jq '.full_lifecycle' | tr -d '\r')
    happy_pct=$(awk "BEGIN {printf \"%d\", $happy * 100 / $total}")
    full_pct=$( awk "BEGIN {printf \"%d\", $full  * 100 / $total}")

    echo "$stats" | jq \
        --argjson happy_pct "$happy_pct" \
        --argjson full_pct  "$full_pct" \
        '{
            total_features:        .total,
            happy_path_pct:        $happy_pct,
            full_lifecycle_pct:    $full_pct,
            happy_path_count:      .happy_path,
            full_lifecycle_count:  .full_lifecycle,
            per_state: {
                happy_path:     .happy_path,
                integration:    .integration,
                edge_cases:     .edge_cases,
                error_handling: .error_handling,
                hardening:      .hardening
            }
        }'
}

get_last_activity() {
    if [ ! -f "$TELEMETRY_FILE" ]; then
        echo "none"
        return
    fi
    read_telemetry | tail -1 | jq -r '.timestamp // "unknown"' 2>/dev/null || echo "unknown"
}

# ─── Full status report ───────────────────────────────────────────────────────

report_full() {
    check_jq

    local project_name
    project_name=$(basename "$PROJECT_DIR")

    local current_gate
    current_gate=$(get_current_gate)

    local gate_count
    gate_count=$(get_gate_count)

    local avg_cal
    avg_cal=$(get_avg_calibration)

    local last_activity
    last_activity=$(get_last_activity)

    echo ""
    echo -e "${BLUE}${BOLD}Project:${NC}  $project_name"
    echo -e "${BLUE}${BOLD}Gate:${NC}     $current_gate  (current)"
    echo ""

    # Completed gates table
    if [ "$gate_count" -gt 0 ]; then
        echo -e "${BOLD}Completed gates:${NC}"
        echo ""

        while IFS= read -r line || [ -n "$line" ]; do
            [ -z "$line" ] && continue
            echo "$line" | jq empty 2>/dev/null || continue

            local gate date ratio
            gate=$(echo "$line" | jq -r '.gate // "?"')
            date=$(echo "$line" | jq -r '.date // ""' | cut -c1-10)
            ratio=$(echo "$line" | jq -r '.delta_ratio // 0')

            # Color calibration ratio
            local ratio_int
            ratio_int=$(echo "$ratio" | awk '{printf "%d", $1 * 100}')
            local ratio_colored
            if [ "$ratio_int" -lt 70 ]; then
                ratio_colored="${YELLOW}${ratio}x${NC}"
            elif [ "$ratio_int" -lt 90 ]; then
                ratio_colored="${YELLOW}${ratio}x${NC}"
            else
                ratio_colored="${GREEN}${ratio}x${NC}"
            fi

            printf "  ${GREEN}✓${NC}  G%-6s  %s  " "$gate" "$date"
            echo -e "${ratio_colored}"
        done < "$CORRECTIONS_FILE"

        echo ""
        printf "  %-20s %s gates, avg %sx calibration\n" "Summary:" "$gate_count" "$avg_cal"
    else
        echo "  No gates completed yet."
    fi

    echo ""
    printf "  %-20s %s\n" "Last activity:" "$last_activity"

    # Lifecycle completion (only shown when FEATURES.json exists)
    local lifecycle_summary
    lifecycle_summary=$(get_lifecycle_summary)
    if [ -n "$lifecycle_summary" ]; then
        echo ""
        echo -e "${BOLD}Feature lifecycle:${NC}"
        echo ""
        echo "  $lifecycle_summary"
        echo ""
    fi
}

# ─── Short one-liner ──────────────────────────────────────────────────────────

report_short() {
    check_jq

    local project_name current_gate gate_count avg_cal
    project_name=$(basename "$PROJECT_DIR")
    current_gate=$(get_current_gate)
    gate_count=$(get_gate_count)
    avg_cal=$(get_avg_calibration)

    echo "${project_name} | gate ${current_gate} | ${gate_count} completed | cal ${avg_cal}x"
}

# ─── JSON output ──────────────────────────────────────────────────────────────

report_json() {
    check_jq

    local current_gate gate_count avg_cal last_activity
    current_gate=$(get_current_gate)
    gate_count=$(get_gate_count)
    avg_cal=$(get_avg_calibration)
    last_activity=$(get_last_activity)

    # Build completed gates array
    local gates_json="[]"
    if [ -f "$CORRECTIONS_FILE" ] && [ "$gate_count" -gt 0 ]; then
        gates_json=$(jq -s '[.[] | {gate: .gate, date: .date, ratio: .delta_ratio}]' \
            "$CORRECTIONS_FILE" 2>/dev/null || echo "[]")
    fi

    # avg_cal may be "n/a" — use null in that case
    local avg_cal_json="null"
    if [ "$avg_cal" != "n/a" ]; then
        avg_cal_json="$avg_cal"
    fi

    local lifecycle_json
    lifecycle_json=$(get_lifecycle_json)

    jq -n \
        --arg project "$(basename "$PROJECT_DIR")" \
        --arg current_gate "$current_gate" \
        --argjson gates_completed "$gate_count" \
        --argjson avg_calibration "$avg_cal_json" \
        --arg last_activity "$last_activity" \
        --argjson completed_gates "$gates_json" \
        --argjson lifecycle "$lifecycle_json" \
        '{
            project: $project,
            current_gate: $current_gate,
            gates_completed: $gates_completed,
            avg_calibration: $avg_calibration,
            last_activity: $last_activity,
            completed_gates: $completed_gates,
            lifecycle: $lifecycle
        }'
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    local command="${1:-full}"

    case "$command" in
        full|status) report_full ;;
        --short|short) report_short ;;
        --json|json) report_json ;;
        *)
            echo "Usage: status-report.sh [full|--short|--json]"
            exit 1
            ;;
    esac
}

main "$@"
