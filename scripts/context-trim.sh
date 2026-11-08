#!/bin/bash
# context-trim.sh
# Meridian episodic memory trimmer (Gate 2.3)
#
# Bounds .meridian/memory/episodic.jsonl to the last N sessions so the event log
# stays context-efficient (PHILOSOPHY principle 3). Older sessions are not
# deleted — they are appended to episodic-archive.jsonl, so history is preserved
# but out of the hot path.
#
# Sessions are ordered by their earliest timestamp; the most recent N are kept.
#
# Usage:
#   context-trim.sh [-n N] [--dry-run]
#
# Config (env):
#   EPISODIC_KEEP_SESSIONS   default number of sessions to keep (default 10)
#
# Exit codes: 0 = ok (trimmed or nothing to do), non-zero = error

set -euo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-.}"
MEM_DIR="$PROJECT_DIR/.meridian/memory"
EPISODIC="$MEM_DIR/episodic.jsonl"
ARCHIVE="$MEM_DIR/episodic-archive.jsonl"

KEEP="${EPISODIC_KEEP_SESSIONS:-10}"
DRY_RUN=0

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
error()   { echo -e "${RED}ERROR:${NC} $1" >&2; exit "${2:-1}"; }
warn()    { echo -e "${YELLOW}WARNING:${NC} $1" >&2; }
success() { echo -e "${GREEN}✓${NC} $1"; }
info()    { echo -e "${BLUE}$1${NC}"; }

while [ $# -gt 0 ]; do
    case "$1" in
        -n)        KEEP="${2:-}"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) echo "Usage: context-trim.sh [-n N] [--dry-run]"; exit 0 ;;
        *)         error "Unknown argument: $1" ;;
    esac
done

command -v jq >/dev/null 2>&1 || error "jq is required for context-trim"
echo "$KEEP" | grep -qE '^[0-9]+$' || error "-n must be a non-negative integer (got '$KEEP')"

if [ ! -f "$EPISODIC" ]; then
    info "No episodic.jsonl to trim ($EPISODIC) — nothing to do"
    exit 0
fi

# Partition events into keep/archive by session recency.
RESULT=$(jq -cs --argjson n "$KEEP" '
    ( group_by(.session_id)
      | map({sid: .[0].session_id, first: (map(.timestamp) | min)})
      | sort_by(.first) | map(.sid) ) as $order
    | ($order | length) as $total
    | ($order[ (if $total > $n then $total - $n else 0 end) : ]) as $keep
    | { total_sessions: $total,
        kept_sessions: ($keep | length),
        keep:    [ .[] | select(.session_id as $s | $keep | index($s)) ],
        archive: [ .[] | select(.session_id as $s | ($keep | index($s)) | not) ] }
' "$EPISODIC")

TOTAL=$(echo "$RESULT" | jq '.total_sessions')
KEPT=$(echo "$RESULT" | jq '.kept_sessions')
ARCHIVE_COUNT=$(echo "$RESULT" | jq '.archive | length')
KEEP_COUNT=$(echo "$RESULT" | jq '.keep | length')

if [ "$ARCHIVE_COUNT" -eq 0 ]; then
    info "episodic.jsonl has $TOTAL session(s) <= keep limit $KEEP — nothing to trim"
    exit 0
fi

if [ "$DRY_RUN" -eq 1 ]; then
    info "[dry-run] would archive $ARCHIVE_COUNT event(s) from $((TOTAL - KEPT)) older session(s)"
    info "[dry-run] would keep $KEEP_COUNT event(s) from the most recent $KEPT session(s)"
    exit 0
fi

# Append archived events, then rewrite episodic with kept events (compact).
echo "$RESULT" | jq -c '.archive[]' >> "$ARCHIVE"
TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
echo "$RESULT" | jq -c '.keep[]' > "$TMP"
mv "$TMP" "$EPISODIC"

success "Trimmed: archived $ARCHIVE_COUNT event(s) from $((TOTAL - KEPT)) older session(s); kept $KEEP_COUNT event(s) from $KEPT session(s)"
success "Archive: $ARCHIVE"
