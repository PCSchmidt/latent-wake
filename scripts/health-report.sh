#!/bin/bash
# health-report.sh
# Meridian Health Report
#
# Generates an engineer-legible health report for the current Meridian project.
# Reads telemetry.jsonl, corrections.jsonl, and memory files.
#
# Usage:
#   health-report.sh              # Full report (default)
#   health-report.sh full         # Full report
#   health-report.sh gates        # Gate calibration only
#   health-report.sh memory       # Memory health only
#   health-report.sh telemetry    # Telemetry summary only
#   health-report.sh session      # Session status only
#   health-report.sh --json       # Machine-readable JSON output

set -euo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-$(pwd)}"
MERIDIAN_DIR="$PROJECT_DIR/.meridian"
TELEMETRY_FILE="$MERIDIAN_DIR/telemetry.jsonl"
SESSION_FILE="$MERIDIAN_DIR/session.json"
CORRECTIONS_FILE="$MERIDIAN_DIR/memory/corrections.jsonl"
SEMANTIC_FILE="$MERIDIAN_DIR/memory/semantic.json"
EPISODIC_FILE="$MERIDIAN_DIR/memory/episodic.jsonl"

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

# ─── Helpers ──────────────────────────────────────────────────────────────────

header() {
    echo ""
    echo -e "${BLUE}${BOLD}━━━ $1 ━━━${NC}"
    echo ""
}

check_jq() {
    if ! command -v jq >/dev/null 2>&1; then
        echo "Error: jq is required for health reports. Install with: apt-get install jq / brew install jq" >&2
        exit 1
    fi
}

read_telemetry() {
    if [ -f "$TELEMETRY_FILE" ]; then
        jq -c '.' "$TELEMETRY_FILE" 2>/dev/null || true
    fi
}

# ─── Section: Session ─────────────────────────────────────────────────────────

section_session() {
    header "Session"

    if [ ! -f "$SESSION_FILE" ]; then
        echo "  No active session."
        echo "  Start one with: bash scripts/session.sh start"
        return 0
    fi

    local session_id project started current_gate tools_used gates_passed errors
    session_id=$(jq -r '.session_id // "unknown"' "$SESSION_FILE" 2>/dev/null || echo "unknown")
    project=$(jq -r '.project // "unknown"' "$SESSION_FILE" 2>/dev/null || echo "unknown")
    started=$(jq -r '.started // "unknown"' "$SESSION_FILE" 2>/dev/null || echo "unknown")
    current_gate=$(jq -r '.current_gate // "unknown"' "$SESSION_FILE" 2>/dev/null || echo "unknown")
    tools_used=$(jq -r '.tools_used // 0' "$SESSION_FILE" 2>/dev/null || echo 0)
    gates_passed=$(jq -r '.gates_passed // 0' "$SESSION_FILE" 2>/dev/null || echo 0)
    errors=$(jq -r '.errors // 0' "$SESSION_FILE" 2>/dev/null || echo 0)

    printf "  %-20s %s\n" "Session ID:" "$session_id"
    printf "  %-20s %s\n" "Project:" "$project"
    printf "  %-20s %s\n" "Started:" "$started"
    printf "  %-20s %s\n" "Current gate:" "$current_gate"
    printf "  %-20s %s\n" "Tools used:" "$tools_used"
    printf "  %-20s %s\n" "Gates passed:" "$gates_passed"
    if [ "$errors" -gt 0 ]; then
        printf "  %-20s " "Errors:"
        echo -e "${RED}${errors}${NC}"
    else
        printf "  %-20s %s\n" "Errors:" "$errors"
    fi
}

# ─── Section: Gate Calibration ────────────────────────────────────────────────

section_gates() {
    header "Gate Calibration"

    if [ ! -f "$CORRECTIONS_FILE" ]; then
        echo "  No corrections data found."
        echo "  Reflexion entries are written at gate completion."
        return 0
    fi

    local total_gates=0

    echo "  Gate   Predicted  Actual  Ratio   Variance"
    echo "  ──────────────────────────────────────────"

    while IFS= read -r line || [ -n "$line" ]; do
        [ -z "$line" ] && continue
        echo "$line" | jq empty 2>/dev/null || continue

        local gate predicted actual ratio variance
        gate=$(echo "$line" | jq -r '.gate // "?"')
        predicted=$(echo "$line" | jq -r '.predicted_hours // 0')
        actual=$(echo "$line" | jq -r '.actual_hours // 0')
        ratio=$(echo "$line" | jq -r '.delta_ratio // 0')
        variance=$(echo "$line" | jq -r '.variance_percent // 0')

        # Color code by ratio: green >=0.9, yellow 0.7-0.9, red <0.7
        local ratio_int
        ratio_int=$(echo "$ratio" | awk '{printf "%d", $1 * 100}')
        local ratio_display variance_display
        if [ "$ratio_int" -lt 70 ]; then
            ratio_display="${RED}${ratio}x${NC}"
        elif [ "$ratio_int" -lt 90 ]; then
            ratio_display="${YELLOW}${ratio}x${NC}"
        else
            ratio_display="${GREEN}${ratio}x${NC}"
        fi

        local variance_int
        variance_int=$(echo "$variance" | awk '{printf "%d", $1}')
        if [ "$variance_int" -lt 0 ]; then
            variance_display="${GREEN}${variance}%${NC}"
        elif [ "$variance_int" -gt 0 ]; then
            variance_display="${YELLOW}+${variance}%${NC}"
        else
            variance_display="0%"
        fi

        printf "  G%-6s %-10s %-8s " "$gate" "${predicted}h" "${actual}h"
        echo -e "${ratio_display}  ${variance_display}"

        total_gates=$((total_gates + 1))
    done < "$CORRECTIONS_FILE"

    if [ "$total_gates" -gt 0 ]; then
        # Aggregate stats via jq -s (handles JSONL correctly)
        local avg_ratio min_ratio max_ratio
        avg_ratio=$(jq -s '[.[].delta_ratio] | add / length | . * 100 | round / 100' \
            "$CORRECTIONS_FILE" 2>/dev/null | awk '{printf "%.2f", $1}')
        min_ratio=$(jq -s '[.[].delta_ratio] | min' \
            "$CORRECTIONS_FILE" 2>/dev/null || echo "?")
        max_ratio=$(jq -s '[.[].delta_ratio] | max' \
            "$CORRECTIONS_FILE" 2>/dev/null || echo "?")

        echo ""
        printf "  %-22s %s\n" "Gates tracked:" "$total_gates"
        printf "  %-22s %sx\n" "Avg operator mult:" "$avg_ratio"
        printf "  %-22s %sx – %sx\n" "Range:" "$min_ratio" "$max_ratio"

        # Assessment
        local avg_int
        avg_int=$(echo "$avg_ratio" | awk '{printf "%d", $1 * 100}')
        echo ""
        if [ "$avg_int" -ge 95 ] && [ "$avg_int" -le 105 ]; then
            echo -e "  ${GREEN}Calibration: EXCELLENT (avg within 5% of target)${NC}"
        elif [ "$avg_int" -ge 85 ] && [ "$avg_int" -le 115 ]; then
            echo -e "  ${GREEN}Calibration: GOOD (avg within 15% of target)${NC}"
        elif [ "$avg_int" -lt 85 ]; then
            echo -e "  ${YELLOW}Calibration: FAST (finishing faster than estimated — tighten estimates)${NC}"
        else
            echo -e "  ${RED}Calibration: SLOW (running over estimate — pad future estimates)${NC}"
        fi
    else
        echo ""
        echo "  No gate data to display."
    fi
}

# ─── Section: Memory Health ───────────────────────────────────────────────────

section_memory() {
    header "Memory Health"

    if [ -f "$SEMANTIC_FILE" ]; then
        local pattern_count high_conf medium_conf low_conf
        pattern_count=$(jq '.patterns | length' "$SEMANTIC_FILE" 2>/dev/null || echo 0)
        high_conf=$(jq '[.patterns[] | select(.confidence == "HIGH")] | length' "$SEMANTIC_FILE" 2>/dev/null || echo 0)
        medium_conf=$(jq '[.patterns[] | select(.confidence == "MEDIUM")] | length' "$SEMANTIC_FILE" 2>/dev/null || echo 0)
        low_conf=$(jq '[.patterns[] | select(.confidence == "LOW")] | length' "$SEMANTIC_FILE" 2>/dev/null || echo 0)

        printf "  %-22s %s\n" "Semantic patterns:" "$pattern_count total"
        printf "    %-18s %s\n" "HIGH confidence:" "$high_conf"
        printf "    %-18s %s\n" "MEDIUM confidence:" "$medium_conf"
        if [ "$low_conf" -gt 0 ]; then
            printf "    %-18s " "LOW confidence:"
            echo -e "${YELLOW}${low_conf}  (needs more validation)${NC}"
        else
            printf "    %-18s %s\n" "LOW confidence:" "$low_conf"
        fi
    else
        echo "  Semantic:           no data"
    fi

    echo ""

    if [ -f "$EPISODIC_FILE" ]; then
        local event_count
        event_count=$(wc -l < "$EPISODIC_FILE" | tr -d ' ')
        printf "  %-22s %s\n" "Episodic events:" "$event_count"
        if [ "$event_count" -gt 200 ]; then
            echo -e "  ${YELLOW}  Warning: >200 events — run: bash scripts/memory-doctor.sh${NC}"
        fi
    else
        echo "  Episodic:           no data"
    fi

    if [ -f "$CORRECTIONS_FILE" ]; then
        local correction_count
        correction_count=$(wc -l < "$CORRECTIONS_FILE" | tr -d ' ')
        printf "  %-22s %s\n" "Corrections:" "$correction_count entries"
    else
        echo "  Corrections:        no data"
    fi
}

# ─── Section: Telemetry ───────────────────────────────────────────────────────

section_telemetry() {
    header "Telemetry"

    if [ ! -f "$TELEMETRY_FILE" ]; then
        echo "  No telemetry data found."
        echo "  Events are written automatically by hooks."
        return 0
    fi

    local all_events
    all_events=$(read_telemetry)

    if [ -z "$all_events" ]; then
        echo "  No valid events in telemetry file."
        return 0
    fi

    local total
    total=$(echo "$all_events" | grep -c . 2>/dev/null || echo 0)
    printf "  %-22s %s\n" "Total events:" "$total"

    echo ""
    echo "  By type:"
    echo "$all_events" | jq -r '.event_type' 2>/dev/null \
        | sort | uniq -c | sort -rn \
        | while read -r count type; do
            printf "    %-25s %s\n" "$type" "$count"
        done

    # Error summary
    local error_count
    error_count=$(echo "$all_events" | jq -r 'select(.event_type == "error")' 2>/dev/null \
        | jq -s 'length' 2>/dev/null || echo 0)
    echo ""
    if [ "$error_count" -gt 0 ]; then
        printf "  %-22s " "Errors:"
        echo -e "${RED}${error_count} — run: bash scripts/telemetry-query.sh errors${NC}"
    else
        printf "  %-22s " "Errors:"
        echo -e "${GREEN}0${NC}"
    fi

    # Top tools
    local tool_lines
    tool_lines=$(echo "$all_events" | jq -r 'select(.event_type == "tool_used") | .tool' 2>/dev/null \
        | sort | uniq -c | sort -rn | head -5 | wc -l | tr -d ' ')
    if [ "$tool_lines" -gt 0 ]; then
        echo ""
        echo "  Top tools:"
        echo "$all_events" | jq -r 'select(.event_type == "tool_used") | .tool' 2>/dev/null \
            | sort | uniq -c | sort -rn | head -5 \
            | while read -r count tool; do
                printf "    %-20s %s\n" "$tool" "$count"
            done
    fi
}

# ─── Full Report ──────────────────────────────────────────────────────────────

report_full() {
    check_jq

    local project_name
    project_name=$(basename "$PROJECT_DIR")

    echo ""
    echo -e "${BLUE}${BOLD}╔══════════════════════════════════════╗${NC}"
    echo -e "${BLUE}${BOLD}║   Meridian Health Report             ║${NC}"
    echo -e "${BLUE}${BOLD}╚══════════════════════════════════════╝${NC}"
    printf "  Project:  %s\n" "$project_name"
    printf "  Report:   %s\n" "$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u)"

    section_session
    section_gates
    section_memory
    section_telemetry

    echo ""
    echo -e "${BLUE}${BOLD}════════════════════════════════════════${NC}"
    echo ""
}

# ─── JSON Output ──────────────────────────────────────────────────────────────

report_json() {
    check_jq

    local gate_count=0
    local avg_ratio="null"
    if [ -f "$CORRECTIONS_FILE" ]; then
        gate_count=$(wc -l < "$CORRECTIONS_FILE" | tr -d ' ')
        if [ "$gate_count" -gt 0 ]; then
            avg_ratio=$(jq -s '[.[].delta_ratio] | add / length | . * 100 | round / 100' \
                "$CORRECTIONS_FILE" 2>/dev/null || echo "null")
        fi
    fi

    local pattern_count=0
    if [ -f "$SEMANTIC_FILE" ]; then
        pattern_count=$(jq '.patterns | length' "$SEMANTIC_FILE" 2>/dev/null || echo 0)
    fi

    local total_events=0
    if [ -f "$TELEMETRY_FILE" ]; then
        total_events=$(read_telemetry | grep -c . 2>/dev/null || echo 0)
    fi

    local session_id="none"
    local current_gate="unknown"
    if [ -f "$SESSION_FILE" ]; then
        session_id=$(jq -r '.session_id // "none"' "$SESSION_FILE" 2>/dev/null || echo "none")
        current_gate=$(jq -r '.current_gate // "unknown"' "$SESSION_FILE" 2>/dev/null || echo "unknown")
    fi

    jq -n \
        --arg project "$(basename "$PROJECT_DIR")" \
        --arg timestamp "$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u)" \
        --arg session_id "$session_id" \
        --arg current_gate "$current_gate" \
        --argjson gates_tracked "$gate_count" \
        --argjson avg_operator_multiplier "$avg_ratio" \
        --argjson semantic_patterns "$pattern_count" \
        --argjson total_events "$total_events" \
        '{
            project: $project,
            timestamp: $timestamp,
            session_id: $session_id,
            current_gate: $current_gate,
            calibration: {
                gates_tracked: $gates_tracked,
                avg_operator_multiplier: $avg_operator_multiplier
            },
            memory: {
                semantic_patterns: $semantic_patterns
            },
            telemetry: {
                total_events: $total_events
            }
        }'
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    local command="${1:-full}"

    case "$command" in
        full|report) report_full ;;
        gates)       check_jq; section_gates ;;
        memory)      check_jq; section_memory ;;
        telemetry)   check_jq; section_telemetry ;;
        session)     check_jq; section_session ;;
        --json|json) report_json ;;
        *)
            echo "Usage: health-report.sh [full|gates|memory|telemetry|session|--json]"
            exit 1
            ;;
    esac
}

main "$@"
