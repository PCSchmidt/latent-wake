#!/bin/bash
# security-audit.sh
# Meridian security posture report (Gate 2.4 — backs the /security skill)
#
# Two views in one:
#   1. The active blocklist (rules from .meridian/security-rules.yaml, by severity)
#   2. What it has actually caught (security events in telemetry.jsonl)
#
# block-dangerous.sh does the live enforcement on every tool call; this script
# is the after-the-fact audit / dashboard.
#
# Usage:
#   security-audit.sh            # full report (rules + telemetry)
#   security-audit.sh rules      # just the active rules
#   security-audit.sh events     # just the security telemetry summary
#
# Exit codes: 0 = ok

set -uo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-$(pwd)}"
RULES_FILE="$PROJECT_DIR/.meridian/security-rules.yaml"
TELEMETRY="$PROJECT_DIR/.meridian/telemetry.jsonl"

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info() { echo -e "${BLUE}$1${NC}"; }

# Emit "id<TAB>severity<TAB>category" per rule (yq if present, awk fallback).
parse_rules() {
    [ -f "$RULES_FILE" ] || return 0
    if command -v yq >/dev/null 2>&1; then
        local n i
        n=$(yq eval '.rules | length' "$RULES_FILE" 2>/dev/null || echo 0)
        for (( i=0; i<n; i++ )); do
            printf '%s\t%s\t%s\n' \
                "$(yq eval ".rules[$i].id" "$RULES_FILE")" \
                "$(yq eval ".rules[$i].severity" "$RULES_FILE")" \
                "$(yq eval ".rules[$i].category" "$RULES_FILE")"
        done
        return 0
    fi
    awk '
        /^[[:space:]]*-[[:space:]]+id:/ { if(have) emit(); have=1; id=v($0); sev=""; cat=""; next }
        /^[[:space:]]+severity:/        { sev=v($0); next }
        /^[[:space:]]+category:/        { cat=v($0); next }
        END { if(have) emit() }
        function v(s){ sub(/^[^:]*:[[:space:]]*/,"",s); return s }
        function emit(){ printf "%s\t%s\t%s\n", id, sev, cat }
    ' "$RULES_FILE"
}

show_rules() {
    info "━━━ Active security rules ━━━"
    if [ ! -f "$RULES_FILE" ]; then
        echo "  (no security-rules.yaml — enforcement inactive)"
        return
    fi
    local total block warn off
    local recs; recs=$(parse_rules)
    total=$(echo "$recs" | grep -c . || true)
    block=$(echo "$recs" | awk -F'\t' '$2=="block"' | grep -c . || true)
    warn=$(echo "$recs"  | awk -F'\t' '$2=="warn"'  | grep -c . || true)
    off=$(echo "$recs"   | awk -F'\t' '$2=="off"'   | grep -c . || true)
    echo "  total: $total   (block: $block, warn: $warn, off: $off)"
    echo ""
    printf "  %-22s %-8s %s\n" "RULE" "SEVERITY" "CATEGORY"
    printf "  %-22s %-8s %s\n" "----" "--------" "--------"
    echo "$recs" | awk -F'\t' 'NF>=2 {printf "  %-22s %-8s %s\n", $1, $2, $3}'
}

show_events() {
    info "━━━ Security events (telemetry) ━━━"
    if [ ! -f "$TELEMETRY" ] || ! command -v jq >/dev/null 2>&1; then
        echo "  (no telemetry or jq unavailable)"
        return
    fi
    # Normalize mixed compact/pretty JSONL, then filter security outcomes.
    local norm; norm=$(jq -c '.' "$TELEMETRY" 2>/dev/null || true)
    local blocked warned
    blocked=$(echo "$norm" | jq -c 'select(.outcome=="blocked")' 2>/dev/null | grep -c . || true)
    warned=$(echo "$norm"  | jq -c 'select(.outcome=="warned")'  2>/dev/null | grep -c . || true)
    echo -e "  ${RED}blocked:${NC} $blocked    ${YELLOW}warned:${NC} $warned"
    local by_rule
    by_rule=$(echo "$norm" | jq -r 'select(.rule != null) | .rule' 2>/dev/null | sort | uniq -c | sort -rn || true)
    if [ -n "$by_rule" ]; then
        echo ""
        echo "  by rule:"
        echo "$by_rule" | sed 's/^/    /'
    fi
}

main() {
    case "${1:-full}" in
        rules)  show_rules ;;
        events) show_events ;;
        full)   show_rules; echo ""; show_events ;;
        *) echo "Usage: security-audit.sh [full|rules|events]" >&2; exit 1 ;;
    esac
}

main "$@"
