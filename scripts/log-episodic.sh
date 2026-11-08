#!/bin/bash
# log-episodic.sh
# Write a validated episodic memory event to .meridian/memory/episodic.jsonl.
#
# Usage:
#   log-episodic.sh <event_type> [--gate <id>] [--outcome <pass|fail|warn|block>] \
#                                [--notes "<text>"] [--artifact <path>] [...]
#
# event_type: session_start | session_end | gate_passed | gate_blocked |
#             stop_event | feature_complete | error_logged
#
# Multiple --artifact flags are supported.
# Reads session_id and project from .meridian/session.json.
#
# Exit codes: 0 = appended, non-zero = error (nothing written)

set -euo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-.}"
MEM_DIR="$PROJECT_DIR/.meridian/memory"
EPISODIC="$MEM_DIR/episodic.jsonl"
SESSION_FILE="$PROJECT_DIR/.meridian/session.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
error()   { echo -e "${RED}ERROR:${NC} $1" >&2; exit "${2:-1}"; }
warn()    { echo -e "${YELLOW}WARN:${NC} $1" >&2; }
success() { echo -e "${GREEN}✓${NC} $1"; }

usage() {
    cat >&2 <<'USAGE'
Usage: log-episodic.sh <event_type> [--gate <id>] [--outcome <pass|fail|warn|block>]
                        [--notes "<text>"] [--artifact <path>] ...

event_type: session_start | session_end | gate_passed | gate_blocked |
            stop_event | feature_complete | error_logged
USAGE
    exit 1
}

[ $# -ge 1 ] || usage
EVENT_TYPE="$1"; shift

GATE=""; OUTCOME=""; NOTES=""
ARTIFACTS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --gate)     GATE="${2:-}"; shift 2 ;;
        --outcome)  OUTCOME="${2:-}"; shift 2 ;;
        --notes)    NOTES="${2:-}"; shift 2 ;;
        --artifact) ARTIFACTS+=("${2:-}"); shift 2 ;;
        -h|--help)  usage ;;
        *)          error "Unknown argument: $1" ;;
    esac
done

# Validate event_type
case "$EVENT_TYPE" in
    session_start|session_end|gate_passed|gate_blocked|stop_event|feature_complete|error_logged) ;;
    *) error "Invalid event_type '$EVENT_TYPE'. Valid: session_start session_end gate_passed gate_blocked stop_event feature_complete error_logged" ;;
esac

command -v jq >/dev/null 2>&1 || error "jq is required"

# Session context
SESSION_ID="00000000"; PROJECT="$(basename "$PROJECT_DIR")"
if [ -f "$SESSION_FILE" ]; then
    SESSION_ID=$(jq -r '.session_id // "00000000"' "$SESSION_FILE" 2>/dev/null || echo "00000000")
    PROJECT=$(jq -r --arg d "$PROJECT" '.project // $d' "$SESSION_FILE" 2>/dev/null || echo "$PROJECT")
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%S")

# Build artifacts JSON array
ARTIFACTS_JSON="[]"
if [ "${#ARTIFACTS[@]}" -gt 0 ]; then
    ARTIFACTS_JSON=$(printf '%s\n' "${ARTIFACTS[@]}" | jq -R . | jq -s .)
fi

# Build entry — include optional fields only when non-empty
ENTRY=$(jq -c -n \
    --arg ts "$TIMESTAMP" --arg et "$EVENT_TYPE" --arg sid "$SESSION_ID" \
    --arg project "$PROJECT" --arg gate "$GATE" --arg outcome "$OUTCOME" \
    --arg notes "$NOTES" --argjson artifacts "$ARTIFACTS_JSON" \
    '{timestamp:$ts, event_type:$et, session_id:$sid, project:$project}
     + (if $gate != "" then {gate:$gate} else {} end)
     + (if $outcome != "" then {outcome:$outcome} else {} end)
     + (if $notes != "" then {notes:$notes} else {} end)
     + (if ($artifacts | length) > 0 then {artifacts:$artifacts} else {} end)')

mkdir -p "$MEM_DIR"

# Write-ahead validation
VALIDATE="$SCRIPT_DIR/validate-memory.sh"
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
[ -f "$EPISODIC" ] && cat "$EPISODIC" > "$TMP"
printf '%s\n' "$ENTRY" >> "$TMP"

if [ -f "$VALIDATE" ]; then
    if ! MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$VALIDATE" episodic "$TMP" >/dev/null 2>&1; then
        error "Episodic event failed schema validation — episodic.jsonl unchanged"
    fi
fi

printf '%s\n' "$ENTRY" >> "$EPISODIC"
success "Episodic event written: $EVENT_TYPE (session $SESSION_ID)"
