#!/bin/bash
# memory-doctor.sh
# Meridian Memory Health Check Script
#
# Validates all memory files and reports health status
# Called by `/memory doctor` command
#
# Usage:
#   memory-doctor.sh [--project-dir <path>]

set -euo pipefail

# Configuration
PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-${1:-.}}"
MEMORY_DIR="$PROJECT_DIR/.meridian/memory"
VALIDATE_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/validate-memory.sh"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Health status
HEALTH_STATUS="GOOD"
WARNINGS=()

#######################################
# Print section header
#######################################
header() {
    echo ""
    echo -e "${BLUE}━━━ $1 ━━━${NC}"
    echo ""
}

#######################################
# Add warning to list
#######################################
add_warning() {
    WARNINGS+=("$1")
    if [ "$HEALTH_STATUS" = "GOOD" ]; then
        HEALTH_STATUS="WARNING"
    fi
}

#######################################
# Mark as critical (fail)
#######################################
set_critical() {
    HEALTH_STATUS="CRITICAL"
}

#######################################
# Validate semantic memory
#######################################
check_semantic() {
    local semantic_file="$MEMORY_DIR/semantic.json"

    if [ ! -f "$semantic_file" ]; then
        echo "⊘ Semantic memory not found (will be created on first use)"
        return 0
    fi

    echo "Checking semantic memory..."

    # Run validation
    if "$VALIDATE_SCRIPT" semantic "$semantic_file" 2>&1 | tee /tmp/semantic_validation.log; then
        local pattern_count
        pattern_count=$(jq '.patterns | length' "$semantic_file" 2>/dev/null || echo "0")

        echo -e "${GREEN}✓${NC} Semantic memory valid: $pattern_count patterns"

        # Check for low-confidence patterns
        if command -v jq >/dev/null 2>&1; then
            local low_confidence
            low_confidence=$(jq '[.patterns[] | select(.confidence == "LOW")] | length' "$semantic_file" 2>/dev/null || echo "0")

            if [ "$low_confidence" -gt 0 ]; then
                add_warning "$low_confidence pattern(s) with LOW confidence (validated_count < 3)"
            fi

            # Check for stale patterns (not validated in 90 days)
            local cutoff_date
            cutoff_date=$(date -u -d "90 days ago" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u -v-90d +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "")

            if [ -n "$cutoff_date" ]; then
                local stale_count
                stale_count=$(jq --arg cutoff "$cutoff_date" '[.patterns[] | select(.last_validated < $cutoff)] | length' "$semantic_file" 2>/dev/null || echo "0")

                if [ "$stale_count" -gt 0 ]; then
                    add_warning "$stale_count pattern(s) not validated in 90+ days (may be stale)"
                fi
            fi
        fi
    else
        echo -e "${RED}✗${NC} Semantic memory validation FAILED"
        set_critical
        cat /tmp/semantic_validation.log
    fi
}

#######################################
# Validate episodic memory
#######################################
check_episodic() {
    local episodic_file="$MEMORY_DIR/episodic.jsonl"

    if [ ! -f "$episodic_file" ]; then
        echo "⊘ Episodic memory not found (will be created on first session)"
        return 0
    fi

    echo "Checking episodic memory..."

    # Run validation
    if "$VALIDATE_SCRIPT" episodic "$episodic_file" 2>&1 | tee /tmp/episodic_validation.log; then
        local event_count
        event_count=$(grep -c . "$episodic_file" 2>/dev/null || echo "0")

        echo -e "${GREEN}✓${NC} Episodic memory valid: $event_count events"

        # Warn if file is getting large
        if [ "$event_count" -gt 200 ]; then
            add_warning "Episodic memory has $event_count events (consider pruning with /memory prune)"
        fi

        # Check for recent errors
        if command -v jq >/dev/null 2>&1; then
            local error_count
            error_count=$(grep '"event_type":"error_logged"' "$episodic_file" 2>/dev/null | wc -l | tr -d ' ' || echo "0")

            if [ "$error_count" -gt 0 ] 2>/dev/null; then
                echo "  ℹ  Found $error_count error events in history"
            fi
        fi
    else
        echo -e "${RED}✗${NC} Episodic memory validation FAILED"
        set_critical
        cat /tmp/episodic_validation.log
    fi
}

#######################################
# Validate corrections memory
#######################################
check_corrections() {
    local corrections_file="$MEMORY_DIR/corrections.jsonl"

    if [ ! -f "$corrections_file" ]; then
        echo "⊘ Corrections memory not found (will be created after first gate)"
        return 0
    fi

    echo "Checking corrections memory..."

    # Run validation
    if "$VALIDATE_SCRIPT" corrections "$corrections_file" 2>&1 | tee /tmp/corrections_validation.log; then
        local correction_count
        correction_count=$(grep -c . "$corrections_file" 2>/dev/null || echo "0")

        echo -e "${GREEN}✓${NC} Corrections memory valid: $correction_count entries"

        # Calculate average calibration
        if command -v jq >/dev/null 2>&1 && [ "$correction_count" -gt 0 ]; then
            local avg_ratio
            avg_ratio=$(jq -s 'map(.delta_ratio) | add / length' "$corrections_file" 2>/dev/null || echo "0")

            if [ "$avg_ratio" != "0" ]; then
                printf "  ℹ  Average calibration: %.2fx " "$avg_ratio"

                # Interpret calibration
                local ratio_int
                ratio_int=$(echo "$avg_ratio * 100" | bc 2>/dev/null || echo "100")

                if [ "$ratio_int" -lt 80 ]; then
                    echo "(consistently overestimating)"
                elif [ "$ratio_int" -gt 120 ]; then
                    echo "(consistently underestimating)"
                else
                    echo "(well calibrated)"
                fi
            fi
        fi
    else
        echo -e "${RED}✗${NC} Corrections memory validation FAILED"
        set_critical
        cat /tmp/corrections_validation.log
    fi
}

#######################################
# Main health check
#######################################
main() {
    header "Memory Health Check"

    # Create memory directory if needed
    mkdir -p "$MEMORY_DIR"

    # Check each memory type
    check_semantic
    echo ""
    check_episodic
    echo ""
    check_corrections

    # Print warnings if any
    if [ ${#WARNINGS[@]} -gt 0 ]; then
        header "Warnings"
        for warning in "${WARNINGS[@]}"; do
            echo -e "${YELLOW}!${NC} $warning"
        done
    fi

    # Print health summary
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    case "$HEALTH_STATUS" in
        GOOD)
            echo -e "Memory health: ${GREEN}GOOD${NC}"
            exit 0
            ;;
        WARNING)
            echo -e "Memory health: ${YELLOW}WARNING${NC}"
            exit 0
            ;;
        CRITICAL)
            echo -e "Memory health: ${RED}CRITICAL${NC}"
            echo ""
            echo "Fix validation errors above before proceeding."
            exit 1
            ;;
    esac
}

main "$@"
