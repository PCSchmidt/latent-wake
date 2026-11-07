#!/bin/bash
# block-dangerous.sh
# Meridian security blocklist enforcement (Gate 2.1)
#
# Scans the pending tool operation against .meridian/security-rules.yaml and
# either blocks it (exit 2) or warns (exit 0, logged), depending on rule
# severity. This is the first hook in Meridian that mechanically blocks — it
# exits 2 on a deterministic dangerous operation, which Claude Code honors by
# refusing to run the tool.
#
# Invocation:
#   - As a subprocess from PreToolUse.sh (normal path); PreToolUse propagates
#     the exit code.
#   - Standalone for testing, with TOOL_NAME and COMMAND/CONTENT set in the env.
#
# Inputs (environment):
#   TOOL_NAME   Tool being run (Bash, Edit, Write, ...)
#   COMMAND     Bash command string (scanned by `target: command` rules)
#   CONTENT     Text written by Edit/Write (scanned by `target: content` rules)
#   TOOL_ARGS   Optional JSON; CONTENT is derived from it if CONTENT is unset
#
# Exit codes:
#   0 = allow (clean, or only warnings raised)
#   2 = block (a `severity: block` rule matched)

# Load common hook logic (logging, block/warn/info, PROJECT_DIR)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/hook-wrapper.sh"

HOOK_NAME="block-dangerous"

RULES_FILE="$PROJECT_DIR/.meridian/security-rules.yaml"
LOG_EVENT="$PROJECT_DIR/scripts/log-event.sh"

#######################################
# Strip one leading and one trailing quote (single or double) from a value.
#######################################
strip_quotes() {
    local v="$1"
    v="${v#\'}"; v="${v%\'}"
    v="${v#\"}"; v="${v%\"}"
    printf '%s' "$v"
}

#######################################
# Emit one tab-separated record per rule: target<TAB>severity<TAB>pattern<TAB>id<TAB>message
# Uses yq when available, otherwise a regular-format awk parser.
#######################################
parse_rules() {
    [ -f "$RULES_FILE" ] || return 0

    if command -v yq >/dev/null 2>&1; then
        local n i
        n=$(yq eval '.rules | length' "$RULES_FILE" 2>/dev/null || echo 0)
        for (( i=0; i<n; i++ )); do
            printf '%s\t%s\t%s\t%s\t%s\n' \
                "$(yq eval ".rules[$i].target"   "$RULES_FILE")" \
                "$(yq eval ".rules[$i].severity" "$RULES_FILE")" \
                "$(yq eval ".rules[$i].pattern"  "$RULES_FILE")" \
                "$(yq eval ".rules[$i].id"       "$RULES_FILE")" \
                "$(yq eval ".rules[$i].message"  "$RULES_FILE")"
        done
        return 0
    fi

    # Fallback: line-based awk parser (no yq required). Relies on the regular
    # 2-space-indent, one-`- id:`-per-rule structure of security-rules.yaml.
    awk '
        /^[[:space:]]*-[[:space:]]+id:/   { if (have) emit(); have=1; id=val($0); tgt=""; sev=""; pat=""; msg=""; next }
        /^[[:space:]]+target:/            { tgt=val($0); next }
        /^[[:space:]]+severity:/          { sev=val($0); next }
        /^[[:space:]]+pattern:/           { pat=val($0); next }
        /^[[:space:]]+message:/           { msg=val($0); next }
        END { if (have) emit() }
        function val(s){ sub(/^[^:]*:[[:space:]]*/, "", s); return s }
        function emit(){ printf "%s\t%s\t%s\t%s\t%s\n", tgt, sev, pat, id, msg }
    ' "$RULES_FILE"
}

#######################################
# Record a security outcome to telemetry (best-effort; never fails the hook).
# Arguments: outcome (blocked|warned), rule id
#######################################
log_security_event() {
    local outcome="$1" rule_id="$2"
    [ -f "$LOG_EVENT" ] || return 0
    bash "$LOG_EVENT" tool_used \
        tool="${TOOL_NAME:-unknown}" hook=PreToolUse \
        outcome="$outcome" rule="$rule_id" >/dev/null 2>&1 || true
}

#######################################
# Resolve the content payload for `target: content` rules.
#######################################
resolve_content() {
    if [ -n "${CONTENT:-}" ]; then
        printf '%s' "$CONTENT"
        return 0
    fi
    if [ -n "${TOOL_ARGS:-}" ] && command -v jq >/dev/null 2>&1; then
        # TOOL_ARGS is the tool_input object (Claude Code contract); keys are
        # direct. Fall back to the legacy .arguments.* shape for safety.
        case "${TOOL_NAME:-}" in
            Write) jq -r '.content // .arguments.content // ""'       <<<"$TOOL_ARGS" 2>/dev/null ;;
            Edit)  jq -r '.new_string // .arguments.new_string // ""' <<<"$TOOL_ARGS" 2>/dev/null ;;
        esac
    fi
}

#######################################
# Main
#######################################
main() {
    if [ ! -f "$RULES_FILE" ]; then
        info "No security-rules.yaml found - security enforcement inactive"
        exit 0
    fi

    local command_input content_input
    command_input="${COMMAND:-}"
    content_input="$(resolve_content)"

    # Nothing to scan
    if [ -z "$command_input" ] && [ -z "$content_input" ]; then
        info "No command or content to scan"
        exit 0
    fi

    local warnings=0
    local target sev pattern id msg input

    while IFS=$'\t' read -r target sev pattern id msg; do
        [ -n "$pattern" ] || continue
        [ "$sev" = "off" ] && continue

        pattern="$(strip_quotes "$pattern")"
        msg="$(strip_quotes "$msg")"

        case "$target" in
            command) input="$command_input" ;;
            content) input="$content_input" ;;
            *)       continue ;;
        esac
        [ -n "$input" ] || continue

        if printf '%s' "$input" | grep -Eq -- "$pattern"; then
            if [ "$sev" = "block" ]; then
                log_security_event blocked "$id"
                block "Security rule '$id': $msg"   # logs BLOCK + exit 2
            else
                warnings=$((warnings + 1))
                log_security_event warned "$id"
                warn "Security rule '$id': $msg"
            fi
        fi
    done < <(parse_rules)

    if [ "$warnings" -gt 0 ]; then
        info "Scan complete - $warnings warning(s), operation allowed"
    else
        info "Scan complete - clean"
    fi
    timer_end
    exit 0
}

main "$@"
