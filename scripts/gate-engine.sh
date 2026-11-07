#!/bin/bash
# gate-engine.sh
# Meridian Gate DAG Engine
#
# Reads .meridian/gates.yaml and enforces the gate dependency graph
# Called by PreToolUse hooks to block operations when gates haven't cleared
#
# Usage:
#   gate-engine.sh validate              # Validate gates.yaml structure
#   gate-engine.sh check-circular        # Detect circular dependencies
#   gate-engine.sh current               # Get current active gate
#   gate-engine.sh can-proceed <gate-id> # Check if gate can proceed
#   gate-engine.sh mark-passed <gate-id> [--approve <token>]  # Pass a gate (deps, artifacts, pre-hooks, approval)

set -euo pipefail

# Configuration
GATES_FILE="${MERIDIAN_PROJECT_DIR:-.}/.meridian/gates.yaml"
STATE_FILE="${MERIDIAN_PROJECT_DIR:-.}/.meridian/gate-state.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Error codes
ERR_MISSING_FILE=1
ERR_INVALID_YAML=2
ERR_CIRCULAR_DEP=3
ERR_MISSING_GATE=4
ERR_DEPENDENCY_NOT_MET=5

#######################################
# Print error message and exit
# Arguments:
#   $1 - Error message
#   $2 - Exit code
#######################################
error() {
    echo -e "${RED}ERROR:${NC} $1" >&2
    exit "${2:-1}"
}

#######################################
# Print warning message
# Arguments:
#   $1 - Warning message
#######################################
warn() {
    echo -e "${YELLOW}WARNING:${NC} $1" >&2
}

#######################################
# Print success message
# Arguments:
#   $1 - Success message
#######################################
success() {
    echo -e "${GREEN}✓${NC} $1"
}

#######################################
# Check if gates.yaml exists
#######################################
check_gates_file() {
    if [ ! -f "$GATES_FILE" ]; then
        error "gates.yaml not found at $GATES_FILE" $ERR_MISSING_FILE
    fi
}

#######################################
# Validate gates.yaml structure
# Uses yq if available, basic checks otherwise
#######################################
validate_gates_yaml() {
    check_gates_file

    # Check if yq is available for proper YAML validation
    if command -v yq >/dev/null 2>&1; then
        # Validate YAML syntax
        if ! yq eval '.' "$GATES_FILE" >/dev/null 2>&1; then
            error "Invalid YAML syntax in $GATES_FILE" $ERR_INVALID_YAML
        fi

        # Check required fields
        local version
        version=$(yq eval '.version' "$GATES_FILE" 2>/dev/null || echo "null")
        if [ "$version" = "null" ]; then
            error "Missing 'version' field in gates.yaml" $ERR_INVALID_YAML
        fi

        local gate_count
        gate_count=$(yq eval '.gates | length' "$GATES_FILE" 2>/dev/null || echo "0")
        if [ "$gate_count" -eq 0 ]; then
            error "No gates defined in gates.yaml" $ERR_INVALID_YAML
        fi

        # Validate each gate has required fields
        for i in $(seq 0 $((gate_count - 1))); do
            local gate_id
            gate_id=$(yq eval ".gates[$i].id" "$GATES_FILE" 2>/dev/null || echo "null")
            if [ "$gate_id" = "null" ]; then
                error "Gate at index $i missing 'id' field" $ERR_INVALID_YAML
            fi

            local gate_type
            gate_type=$(yq eval ".gates[$i].type" "$GATES_FILE" 2>/dev/null || echo "null")
            if [ "$gate_type" = "null" ]; then
                error "Gate '$gate_id' missing 'type' field" $ERR_INVALID_YAML
            fi

            if [ "$gate_type" != "human_approval" ] && [ "$gate_type" != "automated" ]; then
                error "Gate '$gate_id' has invalid type '$gate_type' (must be 'human_approval' or 'automated')" $ERR_INVALID_YAML
            fi
        done

        # Declared checks that don't exist would block `verify` later; say so now.
        local hook
        for hook in $(yq eval '.gates[].hooks.pre[]?' "$GATES_FILE" 2>/dev/null | tr -d '\r' | sort -u); do
            [ -n "$(resolve_hook "$hook")" ] || \
                warn "pre-hook '$hook' is declared but not installed (write it under scripts/ or .claude/hooks/, or remove it)"
        done

        success "gates.yaml structure is valid"
    else
        # Basic validation without yq
        if ! grep -q "^version:" "$GATES_FILE"; then
            error "Missing 'version' field in gates.yaml (install yq for better validation)" $ERR_INVALID_YAML
        fi

        if ! grep -q "^gates:" "$GATES_FILE"; then
            error "Missing 'gates' field in gates.yaml (install yq for better validation)" $ERR_INVALID_YAML
        fi

        warn "yq not found - running basic validation only (install yq for full validation)"
        success "Basic gates.yaml validation passed"
    fi
}

#######################################
# Check for circular dependencies in gate DAG
# Uses depth-first search to detect cycles
#######################################
check_circular_dependencies() {
    check_gates_file

    if ! command -v yq >/dev/null 2>&1; then
        warn "yq not found - cannot check circular dependencies (install yq for this feature)"
        return 0
    fi

    local gate_count
    gate_count=$(yq eval '.gates | length' "$GATES_FILE")

    # Build adjacency list
    declare -A visited
    declare -A rec_stack
    declare -A gate_deps

    # Read all gate IDs and their dependencies
    for i in $(seq 0 $((gate_count - 1))); do
        local gate_id
        gate_id=$(yq eval ".gates[$i].id" "$GATES_FILE")

        local requires
        requires=$(yq eval ".gates[$i].requires[]" "$GATES_FILE" 2>/dev/null || echo "")

        gate_deps["$gate_id"]="$requires"
    done

    # DFS to detect cycles
    for gate_id in "${!gate_deps[@]}"; do
        if [ "${visited[$gate_id]:-}" != "true" ]; then
            if detect_cycle "$gate_id"; then
                error "Circular dependency detected in gate DAG" $ERR_CIRCULAR_DEP
            fi
        fi
    done

    success "No circular dependencies found"
}

#######################################
# Detect cycle using DFS (helper function)
# Arguments:
#   $1 - Gate ID to check
#######################################
detect_cycle() {
    local gate_id="$1"

    visited["$gate_id"]="true"
    rec_stack["$gate_id"]="true"

    # Check all dependencies
    local deps="${gate_deps[$gate_id]:-}"
    for dep in $deps; do
        if [ "${visited[$dep]:-}" != "true" ]; then
            if detect_cycle "$dep"; then
                return 0  # Cycle found
            fi
        elif [ "${rec_stack[$dep]:-}" = "true" ]; then
            echo "Cycle: $gate_id → $dep" >&2
            return 0  # Cycle found
        fi
    done

    rec_stack["$gate_id"]="false"
    return 1  # No cycle
}

#######################################
# Get current active gate
# Returns the gate ID that should be worked on next
#######################################
get_current_gate() {
    check_gates_file

    # Initialize state file if it doesn't exist
    if [ ! -f "$STATE_FILE" ]; then
        echo '{"passed_gates": []}' > "$STATE_FILE"
    fi

    if ! command -v yq >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
        warn "yq or jq not found - cannot determine current gate"
        echo "unknown"
        return 0
    fi

    # Read passed gates from state
    local passed_gates
    passed_gates=$(jq -r '.passed_gates[]' "$STATE_FILE" 2>/dev/null || echo "")

    # Find first gate whose dependencies are all met but hasn't passed yet
    local gate_count
    gate_count=$(yq eval '.gates | length' "$GATES_FILE")

    for i in $(seq 0 $((gate_count - 1))); do
        local gate_id
        gate_id=$(yq eval ".gates[$i].id" "$GATES_FILE")

        # Check if already passed
        if echo "$passed_gates" | grep -qx "$gate_id"; then
            continue
        fi

        # Check if all dependencies are met
        local requires
        requires=$(yq eval ".gates[$i].requires[]" "$GATES_FILE" 2>/dev/null || echo "")

        local deps_met=true
        for dep in $requires; do
            if ! echo "$passed_gates" | grep -qx "$dep"; then
                deps_met=false
                break
            fi
        done

        if [ "$deps_met" = true ]; then
            echo "$gate_id"
            return 0
        fi
    done

    echo "all_complete"
}

#######################################
# Check if a specific gate can proceed
# Arguments:
#   $1 - Gate ID to check
#######################################
can_proceed_gate() {
    local gate_id="$1"
    check_gates_file

    if ! command -v yq >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
        warn "yq or jq not found - cannot check gate status"
        return 0  # Permissive when tools unavailable
    fi

    # Check if gate exists
    local gate_exists
    gate_exists=$(yq eval ".gates[] | select(.id == \"$gate_id\") | .id" "$GATES_FILE" 2>/dev/null || echo "")

    if [ -z "$gate_exists" ]; then
        error "Gate '$gate_id' not found in gates.yaml" $ERR_MISSING_GATE
    fi

    # Check if dependencies are met
    local passed_gates
    passed_gates=$(jq -r '.passed_gates[]' "$STATE_FILE" 2>/dev/null || echo "")

    local requires
    requires=$(yq eval ".gates[] | select(.id == \"$gate_id\") | .requires[]" "$GATES_FILE" 2>/dev/null || echo "")

    for dep in $requires; do
        if ! echo "$passed_gates" | grep -qx "$dep"; then
            echo "Gate '$gate_id' blocked: dependency '$dep' not met" >&2
            return $ERR_DEPENDENCY_NOT_MET
        fi
    done

    success "Gate '$gate_id' can proceed"
    return 0
}

#######################################
# Mark a gate as passed
#
# Refuses (exit 2) unless the gate has actually been earned:
#   1. every gate in `requires` has passed
#   2. every path in `requires_artifacts` exists
#   3. `verify` passes (all hooks.pre, missing hooks block)
#   4. human_approval gates carry --approve <token>, matching approval_token
#      when one is defined. The approver (git user.name) and time are recorded.
# Emits a gate_passed telemetry event.
#
# Arguments:
#   $1 - Gate ID to mark as passed
#   $2.. - optional: --approve <token>
#######################################
refuse_gate() {
    local gate_id="$1" reason="$2"
    local log_event="${MERIDIAN_PROJECT_DIR:-.}/scripts/log-event.sh"
    [ -f "$log_event" ] && bash "$log_event" gate_blocked gate="$gate_id"         reason="mark-passed refused: $reason" >/dev/null 2>&1 || true
    error "Gate '$gate_id' not marked passed: $reason" 2
}

mark_gate_passed() {
    local gate_id="$1"
    shift
    local approve=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --approve) approve="${2:-}"; shift 2 || shift ;;
            *) error "Unknown option for mark-passed: $1" ;;
        esac
    done

    check_gates_file
    if ! command -v jq >/dev/null 2>&1 || ! command -v yq >/dev/null 2>&1; then
        error "mark-passed needs jq and yq to check the gate before passing it" 2
    fi

    local gate
    gate=$(yq eval -o=json ".gates[] | select(.id == \"$gate_id\")" "$GATES_FILE" 2>/dev/null || true)
    [ -n "$gate" ] && [ "$gate" != "null" ] || error "Gate '$gate_id' not found in gates.yaml" $ERR_MISSING_GATE

    # Initialize state file if needed
    if [ ! -f "$STATE_FILE" ]; then
        echo '{"passed_gates": []}' > "$STATE_FILE"
    fi

    # 1. Dependencies
    local dep
    # tr -d '\r': Windows jq ends lines with CRLF, which would corrupt ids and paths
    for dep in $(echo "$gate" | jq -r '.requires // [] | .[]' | tr -d '\r'); do
        if ! jq -e --arg d "$dep" '.passed_gates // [] | index($d)' "$STATE_FILE" >/dev/null 2>&1; then
            refuse_gate "$gate_id" "dependency '$dep' has not passed"
        fi
    done

    # 2. Required artifacts
    local artifact missing=""
    while IFS= read -r artifact; do
        [ -n "$artifact" ] || continue
        [ -e "${MERIDIAN_PROJECT_DIR:-.}/$artifact" ] || missing="${missing:+$missing, }$artifact"
    done < <(echo "$gate" | jq -r '.requires_artifacts // [] | .[]' | tr -d '\r')
    [ -z "$missing" ] || refuse_gate "$gate_id" "required artifact(s) missing: $missing"

    # 3. Pre-hooks (exits 2 on any failure or missing hook)
    verify_gate "$gate_id" >&2

    # 4. Human approval
    local gate_type token approver=""
    gate_type=$(echo "$gate" | jq -r '.type' | tr -d '\r')
    token=$(echo "$gate" | jq -r '.approval_token // empty' | tr -d '\r')
    if [ "$gate_type" = "human_approval" ]; then
        if [ -z "$approve" ]; then
            refuse_gate "$gate_id" "human approval gate: the operator must run mark-passed $gate_id --approve \"${token:-yes}\""
        fi
        if [ -n "$token" ] && [ "$approve" != "$token" ]; then
            refuse_gate "$gate_id" "approval token does not match approval_token for this gate"
        fi
        approver=$(git -C "${MERIDIAN_PROJECT_DIR:-.}" config user.name 2>/dev/null || true)
        approver="${approver:-${USER:-${USERNAME:-unknown}}}"
    fi

    local now new_state
    now=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%S")
    new_state=$(jq --arg g "$gate_id" --arg who "$approver" --arg at "$now" '
        .passed_gates = ((.passed_gates // []) + [$g] | unique)
        | if $who != "" then .approvals = ((.approvals // {}) + {($g): {by: $who, at: $at}}) else . end' "$STATE_FILE")
    echo "$new_state" > "$STATE_FILE"

    success "Gate '$gate_id' marked as passed${approver:+ (approved by $approver)}"

    local log_event="${MERIDIAN_PROJECT_DIR:-.}/scripts/log-event.sh"
    [ -f "$log_event" ] && bash "$log_event" gate_passed gate="$gate_id" gate_type="$gate_type"         approved_by="${approver:-none}" >/dev/null 2>&1 || true

    # Episodic memory (best-effort)
    local log_episodic="${MERIDIAN_PROJECT_DIR:-.}/scripts/log-episodic.sh"
    if [ -f "$log_episodic" ]; then
        MERIDIAN_PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-.}" bash "$log_episodic" gate_passed             --gate "$gate_id" --outcome pass >/dev/null 2>&1 || true
    fi
}

#######################################
# Extract a gate's pre-hooks (hooks.pre) from gates.yaml.
# Arguments: $1 - gate id
# Emits: one hook script name per line (yq when available, awk fallback).
#######################################
get_pre_hooks() {
    local gate_id="$1"

    if command -v yq >/dev/null 2>&1; then
        yq eval ".gates[] | select(.id == \"$gate_id\") | .hooks.pre[]" "$GATES_FILE" 2>/dev/null \
            | grep -v '^null$' || true
        return 0
    fi

    # Fallback: line-based awk parser for the regular 2-space-indent format.
    awk -v target="$gate_id" '
        /^[[:space:]]*-[[:space:]]+id:/ {
            id=$0; sub(/^[^:]*:[[:space:]]*/, "", id);
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", id);
            cur=(id==target); inpre=0; next
        }
        cur && /^[[:space:]]+pre:[[:space:]]*$/ { inpre=1; next }
        cur && inpre && /^[[:space:]]+-[[:space:]]+/ {
            h=$0; sub(/^[[:space:]]+-[[:space:]]+/, "", h);
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", h); print h; next
        }
        cur && inpre && /^[[:space:]]+[A-Za-z_]+:/ { inpre=0 }
    ' "$GATES_FILE"
}

#######################################
# Resolve a hook name to an executable path (.claude/hooks then scripts).
# Arguments: $1 - hook script name
# Echoes resolved path, or nothing if not found.
#######################################
resolve_hook() {
    local name="$1"
    local base="${MERIDIAN_PROJECT_DIR:-.}"
    if [ -f "$base/.claude/hooks/$name" ]; then
        echo "$base/.claude/hooks/$name"
    elif [ -f "$base/scripts/$name" ]; then
        echo "$base/scripts/$name"
    fi
}

#######################################
# Verify a gate: run its hooks.pre in order; block (exit 2) if any fails.
# This is the mechanical gate-enforcement entrypoint (Gate 2.2). It does NOT
# mark the gate passed - run mark-passed after a clean verify.
# Arguments: $1 - gate id
#######################################
verify_gate() {
    local gate_id="$1"
    check_gates_file

    local log_event="${MERIDIAN_PROJECT_DIR:-.}/scripts/log-event.sh"
    local hooks
    hooks=$(get_pre_hooks "$gate_id")

    if [ -z "$hooks" ]; then
        success "Gate '$gate_id' has no pre-hooks to verify"
        return 0
    fi

    local hook path rc=0
    while IFS= read -r hook; do
        [ -n "$hook" ] || continue
        path=$(resolve_hook "$hook")
        if [ -z "$path" ]; then
            # A gate that names a check it cannot run must not pass as if the
            # check ran. Recipes name project-specific checks you write yourself.
            if [ "${MERIDIAN_ALLOW_MISSING_HOOKS:-0}" = "1" ]; then
                warn "Pre-hook '$hook' not found (skipping: MERIDIAN_ALLOW_MISSING_HOOKS=1)"
                continue
            fi
            [ -f "$log_event" ] && bash "$log_event" gate_blocked gate="$gate_id" \
                reason="pre-hook $hook is declared but not installed" >/dev/null 2>&1 || true
            error "Gate '$gate_id' verification FAILED: pre-hook '$hook' is declared in gates.yaml but not installed under .claude/hooks/ or scripts/. Write it, or remove it from the gate (MERIDIAN_ALLOW_MISSING_HOOKS=1 skips missing hooks)." 2
        fi
        echo -e "${YELLOW}→${NC} running pre-hook: $hook" >&2
        rc=0
        # Hooks run with no arguments; they learn which gate they serve from the env.
        MERIDIAN_GATE_ID="$gate_id" bash "$path" >&2 || rc=$?
        if [ "$rc" -eq 2 ]; then
            [ -f "$log_event" ] && bash "$log_event" gate_blocked gate="$gate_id" \
                reason="pre-hook $hook failed" >/dev/null 2>&1 || true
            local log_episodic="${MERIDIAN_PROJECT_DIR:-.}/scripts/log-episodic.sh"
            [ -f "$log_episodic" ] && MERIDIAN_PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-.}" \
                bash "$log_episodic" gate_blocked \
                --gate "$gate_id" --outcome block \
                --notes "pre-hook $hook failed" >/dev/null 2>&1 || true
            error "Gate '$gate_id' verification FAILED: pre-hook '$hook' blocked (exit 2)" 2
        elif [ "$rc" -ne 0 ]; then
            warn "Pre-hook '$hook' exited $rc (non-blocking)"
        fi
    done <<< "$hooks"

    success "Gate '$gate_id' verified - all pre-hooks passed"
    return 0
}

#######################################
# Main command dispatcher
#######################################
main() {
    local command="${1:-}"

    case "$command" in
        validate)
            validate_gates_yaml
            ;;
        check-circular)
            check_circular_dependencies
            ;;
        current)
            get_current_gate
            ;;
        can-proceed)
            if [ $# -lt 2 ]; then
                error "Usage: gate-engine.sh can-proceed <gate-id>"
            fi
            can_proceed_gate "$2"
            ;;
        mark-passed)
            if [ $# -lt 2 ]; then
                error "Usage: gate-engine.sh mark-passed <gate-id> [--approve <token>]"
            fi
            shift
            mark_gate_passed "$@"
            ;;
        verify)
            if [ $# -lt 2 ]; then
                error "Usage: gate-engine.sh verify <gate-id>"
            fi
            verify_gate "$2"
            ;;
        *)
            echo "Meridian Gate Engine"
            echo ""
            echo "Usage:"
            echo "  gate-engine.sh validate              Validate gates.yaml structure"
            echo "  gate-engine.sh check-circular        Detect circular dependencies"
            echo "  gate-engine.sh current               Get current active gate"
            echo "  gate-engine.sh can-proceed <gate-id> Check if gate can proceed"
            echo "  gate-engine.sh verify <gate-id>      Run gate pre-hooks (block on failure)"
            echo "  gate-engine.sh mark-passed <gate-id> [--approve <token>]  Pass a gate after deps, artifacts, pre-hooks, approval"
            echo ""
            echo "Dependencies (optional but recommended):"
            echo "  - yq: YAML parsing and validation"
            echo "  - jq: JSON state management"
            exit 1
            ;;
    esac
}

main "$@"
