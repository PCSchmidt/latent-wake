#!/bin/bash
# cost-report.sh
# Meridian cost report (Gate 2.4 — backs the /costs skill)
#
# Aggregates the cost stub fields (input_tokens, output_tokens, cost_usd) from
# telemetry.jsonl. These fields are reserved Phase-2 stubs (see
# MERIDIAN_ARCHITECTURE_DECISIONS.md Decision 4): until a token-usage data
# source is wired, they are absent and this report will honestly show zero
# captured. The aggregation is built now so cost tracking lights up for free
# the moment events start carrying the fields.
#
# Usage:
#   cost-report.sh            # summary
#   cost-report.sh --json     # machine-readable
#
# Exit codes: 0 = ok

set -uo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-$(pwd)}"
TELEMETRY="$PROJECT_DIR/.meridian/telemetry.jsonl"

BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'

command -v jq >/dev/null 2>&1 || { echo "jq is required for cost-report" >&2; exit 1; }

AS_JSON=0
[ "${1:-}" = "--json" ] && AS_JSON=1

# Aggregate over normalized telemetry.
if [ -f "$TELEMETRY" ]; then
    AGG=$(jq -c '.' "$TELEMETRY" 2>/dev/null | jq -s '{
        events: length,
        events_with_cost: (map(select(.cost_usd != null or .input_tokens != null)) | length),
        input_tokens:  (map(.input_tokens  // 0) | add // 0),
        output_tokens: (map(.output_tokens // 0) | add // 0),
        cost_usd:      (map(.cost_usd      // 0) | add // 0)
    }' 2>/dev/null || echo '{"events":0,"events_with_cost":0,"input_tokens":0,"output_tokens":0,"cost_usd":0}')
else
    AGG='{"events":0,"events_with_cost":0,"input_tokens":0,"output_tokens":0,"cost_usd":0}'
fi

if [ "$AS_JSON" -eq 1 ]; then
    echo "$AGG" | jq '. + {captured: (.events_with_cost > 0), note: "cost fields are Phase-2 stubs; not captured until a token source is wired"}'
    exit 0
fi

events=$(echo "$AGG" | jq -r '.events')
withcost=$(echo "$AGG" | jq -r '.events_with_cost')
intok=$(echo "$AGG" | jq -r '.input_tokens')
outtok=$(echo "$AGG" | jq -r '.output_tokens')
cost=$(echo "$AGG" | jq -r '.cost_usd')

echo -e "${BLUE}━━━ Cost report ━━━${NC}"
echo "  telemetry events     : $events"
echo "  events with cost data: $withcost"
echo "  input tokens         : $intok"
echo "  output tokens        : $outtok"
echo "  estimated cost (USD)  : \$$cost"

if [ "$withcost" -eq 0 ]; then
    echo ""
    echo -e "  ${YELLOW}Note:${NC} no cost data captured yet. input_tokens/output_tokens/cost_usd"
    echo "  are reserved Phase-2 stub fields; this report activates automatically"
    echo "  once a token-usage source populates them (Decision 4)."
fi
