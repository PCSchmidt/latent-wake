#!/bin/bash
# validate-memory.sh
# Meridian Memory Validation Script
#
# Validates memory writes against JSON schema
# Called by PostToolUse hooks when memory files are written
#
# Usage:
#   validate-memory.sh <memory-type> <file-path>
#   validate-memory.sh semantic .meridian/memory/semantic.json
#   validate-memory.sh episodic .meridian/memory/episodic.jsonl
#   validate-memory.sh corrections .meridian/memory/corrections.jsonl

set -euo pipefail

# Configuration
SCHEMA_FILE="${MERIDIAN_PROJECT_DIR:-.}/.meridian/memory-schema.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Error codes
ERR_MISSING_ARGS=1
ERR_INVALID_TYPE=2
ERR_MISSING_FILE=3
ERR_INVALID_JSON=4
ERR_SCHEMA_VALIDATION=5

#######################################
# Print error and exit
#######################################
error() {
    echo -e "${RED}ERROR:${NC} $1" >&2
    exit "${2:-1}"
}

#######################################
# Print warning
#######################################
warn() {
    echo -e "${YELLOW}WARNING:${NC} $1" >&2
}

#######################################
# Print success
#######################################
success() {
    echo -e "${GREEN}✓${NC} $1"
}

#######################################
# Validate semantic memory (JSON)
#######################################
validate_semantic() {
    local file="$1"

    if [ ! -f "$file" ]; then
        error "Semantic memory file not found: $file" $ERR_MISSING_FILE
    fi

    # Check basic JSON validity
    if ! jq empty "$file" 2>/dev/null; then
        error "Invalid JSON in $file" $ERR_INVALID_JSON
    fi

    # Check required fields
    local schema_version
    schema_version=$(jq -r '.schema_version // "missing"' "$file")
    if [ "$schema_version" = "missing" ]; then
        error "Missing schema_version in $file" $ERR_SCHEMA_VALIDATION
    fi

    local memory_type
    memory_type=$(jq -r '.memory_type // "missing"' "$file")
    if [ "$memory_type" != "semantic" ]; then
        error "memory_type must be 'semantic' in $file (found: $memory_type)" $ERR_SCHEMA_VALIDATION
    fi

    # Validate each pattern
    local pattern_count
    pattern_count=$(jq '.patterns | length' "$file" 2>/dev/null || echo "0")

    for i in $(seq 0 $((pattern_count - 1))); do
        # Check required fields
        local pattern_id
        pattern_id=$(jq -r ".patterns[$i].pattern_id // \"missing\"" "$file")
        if [ "$pattern_id" = "missing" ]; then
            error "Pattern at index $i missing pattern_id" $ERR_SCHEMA_VALIDATION
        fi

        # Validate pattern_id format (PAT-XXX-NNN)
        if ! echo "$pattern_id" | grep -qE '^PAT-[A-Z0-9]+-[0-9]{3}$'; then
            error "Invalid pattern_id format: $pattern_id (expected PAT-XXX-NNN)" $ERR_SCHEMA_VALIDATION
        fi

        # Check hash for deduplication
        local hash
        hash=$(jq -r ".patterns[$i].hash // \"missing\"" "$file")
        if [ "$hash" = "missing" ]; then
            error "Pattern $pattern_id missing hash" $ERR_SCHEMA_VALIDATION
        fi
    done

    success "Semantic memory validated: $pattern_count patterns"
}

#######################################
# Validate episodic memory (JSONL)
#######################################
validate_episodic() {
    local file="$1"

    if [ ! -f "$file" ]; then
        # Episodic file may not exist yet - that's OK
        return 0
    fi

    # Validate each line is valid JSON
    local line_num=0
    while IFS= read -r line || [ -n "$line" ]; do
        line_num=$((line_num + 1))

        # Skip empty lines
        if [ -z "$line" ]; then
            continue
        fi

        # Check JSON validity
        if ! echo "$line" | jq empty 2>/dev/null; then
            error "Invalid JSON at line $line_num in $file" $ERR_INVALID_JSON
        fi

        # Check required fields
        local timestamp
        timestamp=$(echo "$line" | jq -r '.timestamp // "missing"')
        if [ "$timestamp" = "missing" ]; then
            error "Missing timestamp at line $line_num in $file" $ERR_SCHEMA_VALIDATION
        fi

        local event_type
        event_type=$(echo "$line" | jq -r '.event_type // "missing"')
        if [ "$event_type" = "missing" ]; then
            error "Missing event_type at line $line_num in $file" $ERR_SCHEMA_VALIDATION
        fi

        # Validate event_type is one of allowed values
        case "$event_type" in
            session_start|session_end|gate_passed|gate_blocked|stop_event|feature_complete|error_logged)
                ;;
            *)
                error "Invalid event_type '$event_type' at line $line_num" $ERR_SCHEMA_VALIDATION
                ;;
        esac

        local session_id
        session_id=$(echo "$line" | jq -r '.session_id // "missing"')
        if [ "$session_id" = "missing" ]; then
            error "Missing session_id at line $line_num in $file" $ERR_SCHEMA_VALIDATION
        fi
    done < "$file"

    success "Episodic memory validated: $line_num events"
}

#######################################
# Validate corrections memory (JSONL)
#######################################
validate_corrections() {
    local file="$1"

    if [ ! -f "$file" ]; then
        # Corrections file may not exist yet - that's OK
        return 0
    fi

    # Validate each line
    local line_num=0
    while IFS= read -r line || [ -n "$line" ]; do
        line_num=$((line_num + 1))

        # Skip empty lines
        if [ -z "$line" ]; then
            continue
        fi

        # Check JSON validity
        if ! echo "$line" | jq empty 2>/dev/null; then
            error "Invalid JSON at line $line_num in $file" $ERR_INVALID_JSON
        fi

        # Check required fields
        local required_fields=("session_id" "gate" "date" "project" "root_cause" "action_next")

        for field in "${required_fields[@]}"; do
            local value
            value=$(echo "$line" | jq -r ".$field // \"missing\"")
            if [ "$value" = "missing" ]; then
                error "Missing $field at line $line_num in $file" $ERR_SCHEMA_VALIDATION
            fi
        done

        # Hours are optional — validate > 0 when present (must appear together)
        for hour_field in predicted_hours actual_hours; do
            local hv
            hv=$(echo "$line" | jq -r ".$hour_field // null")
            if [ "$hv" != "null" ]; then
                local hint
                hint=$(echo "$hv" | awk '{print int($1 * 100)}')
                if [ "$hint" -le 0 ]; then
                    error "$hour_field must be > 0 at line $line_num in $file" $ERR_SCHEMA_VALIDATION
                fi
            fi
        done

    done < "$file"

    success "Corrections memory validated: $line_num entries"
}

#######################################
# Deduplicate semantic patterns by hash
#######################################
deduplicate_semantic() {
    local file="$1"

    if ! command -v jq >/dev/null 2>&1; then
        warn "jq not found - cannot deduplicate"
        return 0
    fi

    # Count patterns before deduplication
    local before
    before=$(jq '.patterns | length' "$file")

    # Deduplicate by hash (keep first occurrence)
    local temp_file
    temp_file=$(mktemp)

    jq '.patterns |= unique_by(.hash)' "$file" > "$temp_file"
    mv "$temp_file" "$file"

    # Count after
    local after
    after=$(jq '.patterns | length' "$file")

    local removed=$((before - after))
    if [ "$removed" -gt 0 ]; then
        success "Removed $removed duplicate patterns"
    fi
}

#######################################
# Main
#######################################
main() {
    if [ $# -lt 2 ]; then
        echo "Usage: validate-memory.sh <memory-type> <file-path>"
        echo ""
        echo "Memory types:"
        echo "  semantic     - Validated patterns (JSON)"
        echo "  episodic     - Session events (JSONL)"
        echo "  corrections  - Reflexion entries (JSONL)"
        exit $ERR_MISSING_ARGS
    fi

    local memory_type="$1"
    local file_path="$2"

    # Check if jq is available
    if ! command -v jq >/dev/null 2>&1; then
        warn "jq not found - running basic validation only (install jq for full validation)"
        # Just check if file is valid JSON/JSONL
        if [ -f "$file_path" ]; then
            if [[ "$file_path" == *.json ]]; then
                if ! python3 -m json.tool "$file_path" >/dev/null 2>&1; then
                    error "Invalid JSON format" $ERR_INVALID_JSON
                fi
            fi
            success "Basic validation passed"
        fi
        return 0
    fi

    # Validate based on type
    case "$memory_type" in
        semantic)
            validate_semantic "$file_path"
            deduplicate_semantic "$file_path"
            ;;
        episodic)
            validate_episodic "$file_path"
            ;;
        corrections)
            validate_corrections "$file_path"
            ;;
        *)
            error "Invalid memory type: $memory_type (must be semantic, episodic, or corrections)" $ERR_INVALID_TYPE
            ;;
    esac
}

main "$@"
