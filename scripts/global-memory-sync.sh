#!/bin/bash
# global-memory-sync.sh
# Meridian cross-project memory sync (Gate 2.3)
#
# Syncs this project's memory with a global store at ~/.meridian/global/ so the
# operator multiplier and validated patterns aggregate across every project
# (PHILOSOPHY.md: "Cross-project learning"). Semantic patterns merge by hash;
# corrections merge by (session_id, gate, date, project) identity, so repeated
# pushes are idempotent.
#
# Usage:
#   global-memory-sync.sh status   # show local vs global counts (default)
#   global-memory-sync.sh push     # merge local memory INTO the global store
#   global-memory-sync.sh pull     # merge global semantic patterns INTO local
#
# Config (env):
#   MERIDIAN_GLOBAL_DIR   global store dir (default $HOME/.meridian/global)
#
# Exit codes: 0 = ok, non-zero = error

set -euo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-.}"
GLOBAL_DIR="${MERIDIAN_GLOBAL_DIR:-$HOME/.meridian/global}"
LOCAL_MEM="$PROJECT_DIR/.meridian/memory"

L_SEMANTIC="$LOCAL_MEM/semantic.json"
L_CORRECTIONS="$LOCAL_MEM/corrections.jsonl"
G_SEMANTIC="$GLOBAL_DIR/semantic.json"
G_CORRECTIONS="$GLOBAL_DIR/corrections.jsonl"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
error()   { echo -e "${RED}ERROR:${NC} $1" >&2; exit "${2:-1}"; }
warn()    { echo -e "${YELLOW}WARNING:${NC} $1" >&2; }
success() { echo -e "${GREEN}✓${NC} $1"; }
info()    { echo -e "${BLUE}$1${NC}"; }

command -v jq >/dev/null 2>&1 || error "jq is required for global memory sync"

now_ts() { date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%S"; }

# Count patterns in a semantic file (0 if missing)
count_patterns() {
    [ -f "$1" ] && jq '.patterns | length' "$1" 2>/dev/null || echo 0
}
# Count non-blank lines in a jsonl file (0 if missing)
count_lines() {
    [ -f "$1" ] && { grep -cve '^[[:space:]]*$' "$1" 2>/dev/null || true; } || echo 0
}

ensure_global() {
    mkdir -p "$GLOBAL_DIR"
    if [ ! -f "$G_SEMANTIC" ]; then
        jq -n --arg ts "$(now_ts)" \
            '{schema_version:"1.0", memory_type:"semantic", project:"global", patterns:[], last_updated:$ts}' \
            > "$G_SEMANTIC"
    fi
    [ -f "$G_CORRECTIONS" ] || : > "$G_CORRECTIONS"
}

do_status() {
    info "Meridian memory — local vs global"
    echo "  local  ($PROJECT_DIR/.meridian/memory)"
    echo "    semantic patterns : $(count_patterns "$L_SEMANTIC")"
    echo "    corrections       : $(count_lines "$L_CORRECTIONS")"
    echo "  global ($GLOBAL_DIR)"
    if [ -d "$GLOBAL_DIR" ]; then
        echo "    semantic patterns : $(count_patterns "$G_SEMANTIC")"
        echo "    corrections       : $(count_lines "$G_CORRECTIONS")"
    else
        echo "    (not initialized — run 'push' to create)"
    fi
}

do_push() {
    ensure_global
    local ts; ts=$(now_ts)

    # Merge semantic patterns by hash
    if [ -f "$L_SEMANTIC" ]; then
        local before after tmp; tmp=$(mktemp)
        before=$(count_patterns "$G_SEMANTIC")
        jq -s --arg ts "$ts" \
            '{schema_version:"1.0", memory_type:"semantic", project:"global",
              patterns: ([.[0].patterns[]?, .[1].patterns[]?] | unique_by(.hash)),
              last_updated:$ts}' \
            "$G_SEMANTIC" "$L_SEMANTIC" > "$tmp" && mv "$tmp" "$G_SEMANTIC"
        after=$(count_patterns "$G_SEMANTIC")
        success "semantic: $((after - before)) new pattern(s) merged ($after total in global)"
    else
        warn "no local semantic.json — skipping semantic push"
    fi

    # Merge corrections by composite identity (idempotent)
    if [ -f "$L_CORRECTIONS" ]; then
        local before after tmp; tmp=$(mktemp)
        before=$(count_lines "$G_CORRECTIONS")
        cat "$G_CORRECTIONS" "$L_CORRECTIONS" \
            | jq -c 'select(. != null)' 2>/dev/null \
            | jq -cs 'unique_by("\(.session_id)|\(.gate)|\(.date)|\(.project)") | .[]' \
            > "$tmp" && mv "$tmp" "$G_CORRECTIONS"
        after=$(count_lines "$G_CORRECTIONS")
        success "corrections: $((after - before)) new entr(ies) merged ($after total in global)"
    else
        warn "no local corrections.jsonl — skipping corrections push"
    fi
}

do_pull() {
    [ -f "$G_SEMANTIC" ] || error "global store not found at $GLOBAL_DIR — run 'push' first"
    mkdir -p "$LOCAL_MEM"

    if [ ! -f "$L_SEMANTIC" ]; then
        jq -n --arg ts "$(now_ts)" --arg p "$(basename "$PROJECT_DIR")" \
            '{schema_version:"1.0", memory_type:"semantic", project:$p, patterns:[], last_updated:$ts}' \
            > "$L_SEMANTIC"
    fi

    local before after tmp; tmp=$(mktemp)
    before=$(count_patterns "$L_SEMANTIC")
    # Merge global patterns into local, keeping the local project label
    jq -s --arg ts "$(now_ts)" \
        '{schema_version: (.[0].schema_version // "1.0"),
          memory_type: "semantic",
          project: (.[0].project // "local"),
          patterns: ([.[0].patterns[]?, .[1].patterns[]?] | unique_by(.hash)),
          last_updated: $ts}' \
        "$L_SEMANTIC" "$G_SEMANTIC" > "$tmp" && mv "$tmp" "$L_SEMANTIC"
    after=$(count_patterns "$L_SEMANTIC")
    success "pulled: $((after - before)) new pattern(s) into local ($after total)"
}

main() {
    case "${1:-status}" in
        status) do_status ;;
        push)   do_push ;;
        pull)   do_pull ;;
        *) error "Unknown command '${1}'. Use: status | push | pull" ;;
    esac
}

main "$@"
