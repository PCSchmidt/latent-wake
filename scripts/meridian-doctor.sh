#!/bin/bash
# meridian-doctor.sh
# Meridian Installation Validator
#
# Validates a Meridian installation: dependencies, project structure, gate
# configuration, hook integrity, and memory health. Prints an engineer-legible
# report and exits non-zero when a CRITICAL problem would silently degrade
# enforcement (the whole point: surface install-time gaps loudly, G5.0).
#
# Usage:
#   meridian-doctor.sh [project-dir]
#   MERIDIAN_PROJECT_DIR=/path/to/project meridian-doctor.sh
#
# Exit codes:
#   0 = GOOD or WARNING (usable, possibly degraded)
#   1 = CRITICAL (a required dependency or invariant is missing)

set -euo pipefail

# Configuration
PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-${1:-.}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MERIDIAN_DIR="$PROJECT_DIR/.meridian"
HOOKS_DIR="$PROJECT_DIR/.claude/hooks"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Health status
HEALTH_STATUS="GOOD"
WARNINGS=()
CRITICALS=()

#######################################
# Print section header
#######################################
header() {
    echo ""
    echo -e "${BLUE}━━━ $1 ━━━${NC}"
}

#######################################
# Record a passing check
#######################################
ok() {
    echo -e "${GREEN}✓${NC} $1"
}

#######################################
# Record a warning (degraded but usable)
#######################################
add_warning() {
    echo -e "${YELLOW}!${NC} $1"
    WARNINGS+=("$1")
    if [ "$HEALTH_STATUS" = "GOOD" ]; then
        HEALTH_STATUS="WARNING"
    fi
}

#######################################
# Record a critical problem (blocks)
#######################################
add_critical() {
    echo -e "${RED}✗${NC} $1"
    CRITICALS+=("$1")
    HEALTH_STATUS="CRITICAL"
}

#######################################
# Informational note (no status change)
#######################################
note() {
    echo -e "  ℹ  $1"
}

#######################################
# Check required and recommended dependencies
#######################################
check_dependencies() {
    header "Dependencies"

    # bash >= 4 (associative arrays used by gate-engine.sh DAG traversal)
    local bash_major="${BASH_VERSINFO[0]:-0}"
    if [ "$bash_major" -ge 4 ]; then
        ok "bash $BASH_VERSION (>= 4 required)"
    else
        add_critical "bash $BASH_VERSION is too old; bash >= 4 required (associative arrays)"
    fi

    # jq — required for all JSON state/memory/telemetry handling
    if command -v jq >/dev/null 2>&1; then
        ok "jq present ($(jq --version 2>/dev/null))"
    else
        add_critical "jq not found — required for memory, telemetry, and gate state. Install: winget install jqlang.jq | choco install jq | brew install jq"
    fi

    # yq — required for gate DAG features (validation, circular-dep, current gate)
    if command -v yq >/dev/null 2>&1; then
        ok "yq present ($(yq --version 2>/dev/null))"
    else
        add_critical "yq not found — gate detection, circular-dependency checking, and gates.yaml validation silently degrade without it (gate-engine returns \"unknown\"). Install: winget install MikeFarah.yq | choco install yq | brew install yq | go install github.com/mikefarah/yq/v4@latest"
    fi

    # awk — used by the yq-less fallback parsers in gate-engine.sh
    if command -v awk >/dev/null 2>&1; then
        ok "awk present"
    else
        add_warning "awk not found — yq-less fallback parsers in gate-engine.sh will not work"
    fi

    # git — required for the Phase 5 commit/CI enforcement boundary
    if command -v git >/dev/null 2>&1; then
        ok "git present ($(git --version 2>/dev/null))"
    else
        add_warning "git not found — the git/CI enforcement boundary (Phase 5) requires git"
    fi
}

#######################################
# Check project structure and schema files
#######################################
check_structure() {
    header "Project Structure"

    if [ ! -d "$MERIDIAN_DIR" ]; then
        add_critical ".meridian/ not found at $MERIDIAN_DIR — not a Meridian project (run install.sh)"
        return 0
    fi
    ok ".meridian/ present"

    # Schema files (tracked, ship with the framework) — check presence and parse
    local schema
    for schema in memory-schema.json telemetry-schema.json gate-schema.yaml features-schema.json; do
        if [ ! -f "$MERIDIAN_DIR/$schema" ]; then
            add_warning "schema missing: .meridian/$schema"
            continue
        fi
        case "$schema" in
            *.json)
                if command -v jq >/dev/null 2>&1; then
                    if jq empty "$MERIDIAN_DIR/$schema" >/dev/null 2>&1; then
                        ok "schema valid (JSON): $schema"
                    else
                        add_critical "schema malformed JSON: $schema (run: jq empty .meridian/$schema)"
                    fi
                else
                    ok "schema present: $schema (JSON not parsed — jq missing)"
                fi
                ;;
            *.yaml)
                if command -v yq >/dev/null 2>&1; then
                    if yq '.' "$MERIDIAN_DIR/$schema" >/dev/null 2>&1; then
                        ok "schema valid (YAML): $schema"
                    else
                        add_critical "schema malformed YAML: $schema (run: yq . .meridian/$schema)"
                    fi
                else
                    ok "schema present: $schema (YAML not parsed — yq missing)"
                fi
                ;;
        esac
    done

    # Core scripts that the hooks depend on
    local s
    for s in gate-engine.sh validate-memory.sh log-event.sh write-reflexion.sh session.sh log-episodic.sh; do
        if [ -f "$SCRIPT_DIR/$s" ]; then
            ok "core script present: $s"
        else
            add_critical "core script missing: scripts/$s"
        fi
    done
}

#######################################
# Validate gate configuration if present
#######################################
check_gates() {
    header "Gate Configuration"

    local gates_file="$MERIDIAN_DIR/gates.yaml"
    if [ ! -f "$gates_file" ]; then
        note "No .meridian/gates.yaml (framework repo, or project not yet initialized with a recipe)."
        note "End-user projects install a gates.yaml via install.sh --recipe <name>."
        return 0
    fi

    if ! command -v yq >/dev/null 2>&1; then
        add_critical "gates.yaml present but yq missing — cannot validate the gate DAG (see Dependencies above)"
        return 0
    fi

    if MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$SCRIPT_DIR/gate-engine.sh" validate >/dev/null 2>&1; then
        ok "gates.yaml structure valid"
    else
        add_critical "gates.yaml failed structural validation (run: gate-engine.sh validate)"
    fi

    if MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$SCRIPT_DIR/gate-engine.sh" check-circular >/dev/null 2>&1; then
        ok "no circular dependencies in gate DAG"
    else
        add_critical "circular dependency detected in gate DAG (run: gate-engine.sh check-circular)"
    fi
}

#######################################
# Check hook integrity (sourced-not-executed contract)
#######################################
check_hooks() {
    header "Hook Integrity"

    local wrapper="$HOOKS_DIR/hook-wrapper.sh"
    if [ ! -f "$wrapper" ]; then
        add_warning ".claude/hooks/hook-wrapper.sh not found — hooks not installed in this project"
        return 0
    fi
    ok "hook-wrapper.sh present"

    # The wrapper must refuse direct execution (sourced-not-executed contract)
    if grep -q "should be sourced, not executed" "$wrapper"; then
        ok "hook-wrapper.sh guards against direct execution"
    else
        add_critical "hook-wrapper.sh is missing its sourced-not-executed guard"
    fi

    # Entry hooks should source the wrapper, not re-implement it; also check syntax
    local h
    for h in PreToolUse.sh PostToolUse.sh SessionStart.sh; do
        [ -f "$HOOKS_DIR/$h" ] || continue
        if grep -q "hook-wrapper.sh" "$HOOKS_DIR/$h"; then
            ok "$h sources hook-wrapper.sh"
        else
            add_warning "$h does not source hook-wrapper.sh"
        fi
        if bash -n "$HOOKS_DIR/$h" 2>/dev/null; then
            ok "$h syntax OK"
        else
            add_critical "$h has a bash syntax error (run: bash -n .claude/hooks/$h)"
        fi
    done

    # .claude/settings.json must exist and be valid JSON for hook registration
    local settings="$PROJECT_DIR/.claude/settings.json"
    if [ -f "$settings" ]; then
        if command -v jq >/dev/null 2>&1; then
            if jq empty "$settings" >/dev/null 2>&1; then
                ok ".claude/settings.json present and valid JSON"
            else
                add_critical ".claude/settings.json is malformed JSON (run: jq empty .claude/settings.json)"
            fi
        else
            ok ".claude/settings.json present (JSON not validated — jq missing)"
        fi
    else
        add_warning ".claude/settings.json not found — hooks (SessionStart, PreToolUse, PostToolUse) may not be registered with Claude Code"
    fi
}

#######################################
# Validate memory files if present
#######################################
check_memory() {
    header "Memory Integrity"

    local mem_dir="$MERIDIAN_DIR/memory"
    local validate="$SCRIPT_DIR/validate-memory.sh"

    if [ ! -d "$mem_dir" ]; then
        note "No memory directory yet (created on first session)."
        return 0
    fi
    if [ ! -f "$validate" ]; then
        add_warning "validate-memory.sh not found — skipping memory validation"
        return 0
    fi

    local pair type file
    for pair in "semantic:semantic.json" "episodic:episodic.jsonl" "corrections:corrections.jsonl"; do
        type="${pair%%:*}"
        file="$mem_dir/${pair##*:}"
        [ -f "$file" ] || continue
        if MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$validate" "$type" "$file" >/dev/null 2>&1; then
            ok "$type memory valid"
        else
            add_critical "$type memory failed validation (run: validate-memory.sh $type $file)"
        fi
    done
}

#######################################
# Main
#######################################
main() {
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Meridian Doctor — installation health check"
    echo "Project: $PROJECT_DIR"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    check_dependencies
    check_structure
    check_gates
    check_hooks
    check_memory

    # Summary
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if [ ${#CRITICALS[@]} -gt 0 ]; then
        echo -e "Installation health: ${RED}CRITICAL${NC} (${#CRITICALS[@]} blocking issue(s), ${#WARNINGS[@]} warning(s))"
        echo ""
        echo "Resolve these before relying on enforcement:"
        local c
        for c in "${CRITICALS[@]}"; do
            echo -e "  ${RED}✗${NC} $c"
        done
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        exit 1
    elif [ ${#WARNINGS[@]} -gt 0 ]; then
        echo -e "Installation health: ${YELLOW}WARNING${NC} (${#WARNINGS[@]} warning(s), usable but degraded)"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        exit 0
    else
        echo -e "Installation health: ${GREEN}GOOD${NC}"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        exit 0
    fi
}

main "$@"
