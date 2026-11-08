#!/bin/bash
# PostToolUse.sh
# Meridian PostToolUse Hook
#
# Runs AFTER tool execution to:
# - Validate memory file writes against schema
# - Log telemetry data
# - Update gate state if artifacts are complete
# - Detect and report errors
#
# Exit codes:
#   0 = Success
#   1 = Warning (non-blocking)
#   2 = Block (should not happen in PostToolUse, but available)

# Load common hook logic
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/hook-wrapper.sh"

HOOK_NAME="PostToolUse"

#######################################
# Validate memory file if modified
#######################################
validate_memory_file() {
    local file_path="$1"

    # Determine memory type from file path
    local memory_type=""
    if [[ "$file_path" == *"/semantic.json" ]]; then
        memory_type="semantic"
    elif [[ "$file_path" == *"/episodic.jsonl" ]]; then
        memory_type="episodic"
    elif [[ "$file_path" == *"/corrections.jsonl" ]]; then
        memory_type="corrections"
    else
        return 0  # Not a memory file
    fi

    info "Validating $memory_type memory file: $file_path"

    # Run validation
    local validate_script="$PROJECT_DIR/scripts/validate-memory.sh"
    if [ ! -f "$validate_script" ]; then
        warn "validate-memory.sh not found - skipping validation"
        return 0
    fi

    if bash "$validate_script" "$memory_type" "$file_path" >> "$LOG_FILE" 2>&1; then
        info "Memory validation passed: $memory_type"
    else
        error "Memory validation failed: $memory_type - see $LOG_FILE for details"
    fi
}

#######################################
# Log telemetry event via log-event.sh
#######################################
log_telemetry() {
    if [ ! -d "$PROJECT_DIR/.meridian" ]; then
        return 0
    fi

    local log_event_script="$PROJECT_DIR/scripts/log-event.sh"

    if [ -f "$log_event_script" ]; then
        local outcome="allowed"
        MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$log_event_script" tool_used \
            "tool=${TOOL_NAME:-unknown}" \
            "hook=$HOOK_NAME" \
            "outcome=$outcome" 2>/dev/null || true
        info "Telemetry logged"
    fi
}

#######################################
# Main hook logic
#######################################
main() {
    # Parse tool use from stdin (if provided)
    if [ -t 0 ]; then
        # No stdin (running standalone for testing)
        info "Running in test mode (no stdin)"
    else
        parse_tool_use
    fi

    info "Tool: ${TOOL_NAME:-unknown}"

    # Check if we're in a Meridian project
    if ! check_meridian_project; then
        # Not a Meridian project - nothing to validate
        info "Not a Meridian project - no validation needed"
        timer_end
        exit 0
    fi

    # Tool-specific post-execution checks
    case "$TOOL_NAME" in
        Edit|Write)
            # Check if a memory file was modified
            if [[ "$FILE_PATH" == *"/.meridian/memory/"* ]]; then
                validate_memory_file "$FILE_PATH"
            fi
            ;;

        Bash)
            # Check exit code if available
            if [ -n "${EXIT_CODE:-}" ] && [ "$EXIT_CODE" != "0" ]; then
                warn "Command failed with exit code $EXIT_CODE: $COMMAND"
            fi
            ;;
    esac

    # Log telemetry
    log_telemetry

    # Finish
    info "Post-execution validation complete"
    timer_end
    exit 0
}

# Run main
main "$@"
