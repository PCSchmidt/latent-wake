#!/bin/bash
# hook-wrapper.sh
# Meridian Hook Wrapper - Common logic for all Claude Code hooks
#
# Provides:
# - Structured logging to .meridian/hooks.log
# - Error handling with exit code 2 (blocks tool execution)
# - Hook execution timing
# - Environment variable access
#
# Exit codes:
#   0 = Success (allow tool execution)
#   1 = Error (allow but warn)
#   2 = Block (prevent tool execution)

set -euo pipefail

# Configuration
PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-$(pwd)}"
LOG_FILE="$PROJECT_DIR/.meridian/hooks.log"
HOOK_NAME="${HOOK_NAME:-unknown}"

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

#######################################
# Log a message with timestamp
# Arguments:
#   $1 - Log level (INFO, WARN, ERROR, BLOCK)
#   $2 - Message
#######################################
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%S" 2>/dev/null)

    # Ensure log directory exists
    mkdir -p "$(dirname "$LOG_FILE")"

    # Write to log file
    echo "$timestamp [$level] [$HOOK_NAME] $message" >> "$LOG_FILE"

    # Also output to stderr for visibility
    case "$level" in
        INFO)
            echo -e "${BLUE}[${HOOK_NAME}]${NC} $message" >&2
            ;;
        WARN)
            echo -e "${YELLOW}[${HOOK_NAME} WARNING]${NC} $message" >&2
            ;;
        ERROR)
            echo -e "${RED}[${HOOK_NAME} ERROR]${NC} $message" >&2
            ;;
        BLOCK)
            echo -e "${RED}[${HOOK_NAME} BLOCKED]${NC} $message" >&2
            ;;
    esac
}

#######################################
# Block tool execution with message
# Arguments:
#   $@ - Block reason
#######################################
block() {
    log BLOCK "$*"
    # Every block also becomes a telemetry event, so blocks can be counted and
    # labelled later (scripts/dogfood.sh). Best-effort: never changes the exit.
    local log_event="$PROJECT_DIR/scripts/log-event.sh"
    if [ -f "$log_event" ]; then
        MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$log_event" hook_blocked \
            hook="$HOOK_NAME" tool="${TOOL_NAME:-none}" reason="$*" >/dev/null 2>&1 || true
    fi
    exit 2
}

#######################################
# Report error but allow execution
# Arguments:
#   $@ - Error message
#######################################
error() {
    log ERROR "$*"
    exit 1
}

#######################################
# Report warning
# Arguments:
#   $@ - Warning message
#######################################
warn() {
    log WARN "$*"
}

#######################################
# Report info
# Arguments:
#   $@ - Info message
#######################################
info() {
    log INFO "$*"
}

#######################################
# Check if we're in a Meridian project
#######################################
check_meridian_project() {
    if [ ! -f "$PROJECT_DIR/.meridian/gate-schema.yaml" ] && [ ! -f "$PROJECT_DIR/.meridian/gates.yaml" ]; then
        warn "Not a Meridian project - hooks running in permissive mode"
        return 1
    fi
    return 0
}

#######################################
# Get current gate from state
#######################################
get_current_gate() {
    local state_file="$PROJECT_DIR/.meridian/gate-state.json"

    if [ ! -f "$state_file" ]; then
        echo "unknown"
        return 0
    fi

    if command -v jq >/dev/null 2>&1; then
        local current_gate
        current_gate=$("$PROJECT_DIR/scripts/gate-engine.sh" current 2>/dev/null || echo "unknown")
        echo "$current_gate"
    else
        echo "unknown"
    fi
}

#######################################
# Parse tool use from stdin or environment
# Reads JSON from stdin and extracts tool information
# Falls back to environment variables if no stdin
#######################################
parse_tool_use() {
    # If TOOL_NAME is already set in environment, use that
    if [ -n "${TOOL_NAME:-}" ]; then
        info "Using TOOL_NAME from environment: $TOOL_NAME"
        return 0
    fi

    # Otherwise try to parse from stdin
    if command -v jq >/dev/null 2>&1; then
        # Check if stdin is available
        if [ ! -t 0 ]; then
            # Read stdin and parse JSON.
            #
            # Claude Code's live PreToolUse/PostToolUse contract delivers:
            #   { "hook_event_name": "PreToolUse",
            #     "tool_name": "Bash",
            #     "tool_input": { "command": "...", "file_path": "...", ... } }
            # (PostToolUse additionally carries "tool_response").
            #
            # We read those real keys first and fall back to the legacy
            # .tool / .arguments shape for backward compatibility. See
            # docs/tier1-verification.md for the full contract and why this
            # matters (the env-var test path never exercised this).
            local tool_data
            tool_data=$(cat)

            TOOL_NAME=$(echo "$tool_data" | jq -r '.tool_name // .tool // "unknown"')
            export TOOL_NAME
            TOOL_ARGS=$(echo "$tool_data" | jq -c '.tool_input // .arguments // {}')
            export TOOL_ARGS

            # Common parameters, extracted from tool_input (legacy: arguments).
            FILE_PATH=$(echo "$tool_data" | jq -r '.tool_input.file_path // .arguments.file_path // ""')
            export FILE_PATH
            COMMAND=$(echo "$tool_data" | jq -r '.tool_input.command // .arguments.command // ""')
            export COMMAND

            # Written text for content-target security scanning (Edit/Write).
            case "$TOOL_NAME" in
                Write)
                    CONTENT=$(echo "$tool_data" | jq -r '.tool_input.content // .arguments.content // ""')
                    export CONTENT
                    ;;
                Edit)
                    CONTENT=$(echo "$tool_data" | jq -r '.tool_input.new_string // .arguments.new_string // ""')
                    export CONTENT
                    ;;
            esac
        fi
    else
        warn "jq not available - tool parsing disabled"
    fi

    # Set default if still not set
    if [ -z "${TOOL_NAME:-}" ]; then
        export TOOL_NAME="unknown"
    fi
}

#######################################
# Timer start
#######################################
timer_start() {
    HOOK_START_TIME=$(date +%s 2>/dev/null || echo "0")
}

#######################################
# Timer end and log duration
#######################################
timer_end() {
    if [ "${HOOK_START_TIME:-0}" != "0" ]; then
        local end_time
        end_time=$(date +%s 2>/dev/null || echo "0")
        local duration=$((end_time - HOOK_START_TIME))
        info "Hook executed in ${duration}s"
    fi
}

#######################################
# Export hook wrapper functions
# Makes functions available to hook scripts that source this file
#######################################
export -f log block error warn info check_meridian_project get_current_gate parse_tool_use timer_start timer_end

#######################################
# Main execution wrapper
# Usage: source hook-wrapper.sh, then call your hook logic
#######################################
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    # Script is being executed directly, not sourced
    echo "hook-wrapper.sh should be sourced, not executed directly"
    echo ""
    echo "Usage in your hook script:"
    echo "  #!/bin/bash"
    echo "  source \"\$(dirname \"\${BASH_SOURCE[0]}\")/hook-wrapper.sh\""
    echo "  HOOK_NAME=\"my-hook\""
    echo "  # Your hook logic here"
    exit 1
fi

# Hook wrapper loaded successfully
info "Hook wrapper loaded for $HOOK_NAME"
timer_start
