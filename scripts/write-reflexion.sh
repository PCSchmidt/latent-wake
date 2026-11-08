#!/bin/bash
# write-reflexion.sh
# Meridian reflexion writer (Gate 2.3)
#
# Appends a calibration/reflexion entry to .meridian/memory/corrections.jsonl,
# computing delta_ratio and variance_percent from predicted vs actual hours.
# This formalizes the manual jq-append done at each gate close. It validates the
# entry against the memory schema BEFORE appending (write-ahead validation) so a
# malformed entry can never corrupt the corrections log.
#
# Usage:
#   write-reflexion.sh --gate <id> --predicted <h> --actual <h> \
#                       --root-cause "<why>" --action-next "<next>" \
#                       [--errors-open N] [--errors-close N]
#
# Session id and project are read from .meridian/session.json.
#
# Exit codes: 0 = appended, non-zero = validation/usage error (nothing written)

set -euo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-.}"
MEM_DIR="$PROJECT_DIR/.meridian/memory"
CORRECTIONS="$MEM_DIR/corrections.jsonl"
SESSION_FILE="$PROJECT_DIR/.meridian/session.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
error()   { echo -e "${RED}ERROR:${NC} $1" >&2; exit "${2:-1}"; }
warn()    { echo -e "${YELLOW}WARNING:${NC} $1" >&2; }
success() { echo -e "${GREEN}✓${NC} $1"; }

usage() {
    cat >&2 <<'USAGE'
Usage: write-reflexion.sh --gate <id> --root-cause "<why>" --action-next "<next>" \
                          [--predicted <h> --actual <h>] [--errors-open N] [--errors-close N]

--predicted and --actual are optional but must be provided together.
When omitted, the entry is written without calibration metrics.
USAGE
    exit 1
}

# Defaults
GATE=""; PREDICTED=""; ACTUAL=""; ROOT_CAUSE=""; ACTION_NEXT=""
ERRORS_OPEN=0; ERRORS_CLOSE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --gate)         GATE="${2:-}"; shift 2 ;;
        --predicted)    PREDICTED="${2:-}"; shift 2 ;;
        --actual)       ACTUAL="${2:-}"; shift 2 ;;
        --root-cause)   ROOT_CAUSE="${2:-}"; shift 2 ;;
        --action-next)  ACTION_NEXT="${2:-}"; shift 2 ;;
        --errors-open)  ERRORS_OPEN="${2:-0}"; shift 2 ;;
        --errors-close) ERRORS_CLOSE="${2:-0}"; shift 2 ;;
        -h|--help)      usage ;;
        *)              error "Unknown argument: $1" ;;
    esac
done

# Required fields
[ -n "$GATE" ]        || { warn "missing --gate"; usage; }
[ -n "$ROOT_CAUSE" ]  || { warn "missing --root-cause"; usage; }
[ -n "$ACTION_NEXT" ] || { warn "missing --action-next"; usage; }

# Hours are optional — but must be provided together (can't compute delta from one)
if [ -n "$PREDICTED" ] && [ -z "$ACTUAL" ]; then
    error "--actual is required when --predicted is provided"
fi
if [ -n "$ACTUAL" ] && [ -z "$PREDICTED" ]; then
    error "--predicted is required when --actual is provided"
fi

command -v jq >/dev/null 2>&1 || error "jq is required to write reflexion entries"

# When hours provided, validate numerics > 0 and compute derived metrics
DELTA_RATIO=""; VARIANCE=""
if [ -n "$PREDICTED" ] && [ -n "$ACTUAL" ]; then
    awk -v p="$PREDICTED" 'BEGIN{exit !(p+0 > 0)}' || error "--predicted must be a positive number"
    awk -v a="$ACTUAL"    'BEGIN{exit !(a+0 > 0)}' || error "--actual must be a positive number"
    DELTA_RATIO=$(awk -v p="$PREDICTED" -v a="$ACTUAL" 'BEGIN{printf "%.2f", p/a}')
    VARIANCE=$(awk -v p="$PREDICTED" -v a="$ACTUAL" 'BEGIN{printf "%.1f", (a-p)/p*100}')
fi

# Session context
SESSION_ID="00000000"; PROJECT="$(basename "$PROJECT_DIR")"
if [ -f "$SESSION_FILE" ]; then
    SESSION_ID=$(jq -r '.session_id // "00000000"' "$SESSION_FILE" 2>/dev/null || echo "00000000")
    PROJECT=$(jq -r --arg d "$PROJECT" '.project // $d' "$SESSION_FILE" 2>/dev/null || echo "$PROJECT")
fi
DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%S")

# Build the entry — include hour fields only when both are present
if [ -n "$PREDICTED" ] && [ -n "$ACTUAL" ]; then
    ENTRY=$(jq -c -n \
        --arg sid "$SESSION_ID" --arg gate "$GATE" --arg date "$DATE" --arg project "$PROJECT" \
        --argjson predicted "$PREDICTED" --argjson actual "$ACTUAL" \
        --argjson delta "$DELTA_RATIO" --argjson variance "$VARIANCE" \
        --arg root "$ROOT_CAUSE" --arg next "$ACTION_NEXT" \
        --argjson eopen "$ERRORS_OPEN" --argjson eclose "$ERRORS_CLOSE" \
        '{session_id:$sid, gate:$gate, date:$date, project:$project,
          predicted_hours:$predicted, actual_hours:$actual,
          delta_ratio:$delta, variance_percent:$variance,
          root_cause:$root, action_next:$next,
          errors_open:$eopen, errors_close:$eclose}')
else
    ENTRY=$(jq -c -n \
        --arg sid "$SESSION_ID" --arg gate "$GATE" --arg date "$DATE" --arg project "$PROJECT" \
        --arg root "$ROOT_CAUSE" --arg next "$ACTION_NEXT" \
        --argjson eopen "$ERRORS_OPEN" --argjson eclose "$ERRORS_CLOSE" \
        '{session_id:$sid, gate:$gate, date:$date, project:$project,
          root_cause:$root, action_next:$next,
          errors_open:$eopen, errors_close:$eclose}')
fi

mkdir -p "$MEM_DIR"

# Write-ahead validation: validate the would-be-appended file in a temp copy.
VALIDATE="$SCRIPT_DIR/validate-memory.sh"
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
[ -f "$CORRECTIONS" ] && cat "$CORRECTIONS" > "$TMP"
printf '%s\n' "$ENTRY" >> "$TMP"

if [ -f "$VALIDATE" ]; then
    if ! MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$VALIDATE" corrections "$TMP" >/dev/null 2>&1; then
        error "Reflexion entry failed schema validation - corrections.jsonl unchanged"
    fi
fi

# Commit the append
printf '%s\n' "$ENTRY" >> "$CORRECTIONS"

# Telemetry (best-effort)
LOG_EVENT="$SCRIPT_DIR/log-event.sh"
if [ -f "$LOG_EVENT" ]; then
    MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$LOG_EVENT" memory_write \
        memory_type=corrections validation=pass >/dev/null 2>&1 || true
fi

success "Reflexion written: gate $GATE (predicted ${PREDICTED}h, actual ${ACTUAL}h, delta ${DELTA_RATIO}x, variance ${VARIANCE}%)"
