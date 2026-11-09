#!/usr/bin/env bash
# reopen-gate.sh: reopen passed gates after an approved contract amendment.
#
# Meridian's rollback-gate.sh removes gates by lexical order and keeps no
# record of why. This removes exactly the named gates, moves any owner
# approval into a history list, and records the reason, so the audit trail
# shows the gate was passed, reopened, and passed again.
#
# Owner-only: run it in your own terminal, then re-approve the gates the
# usual way. An agent must not run this.
#
# Usage:
#   bash scripts/reopen-gate.sh --reason "contract v2: Class A population" data_contract pipeline_validated
#   bash scripts/reopen-gate.sh --dry-run --reason "..." data_contract

set -euo pipefail

STATE=".meridian/gate-state.json"
REASON="" ; DRY=0 ; GATES=()
while [ $# -gt 0 ]; do
    case "$1" in
        --reason)  REASON="${2:-}"; shift 2 ;;
        --dry-run) DRY=1; shift ;;
        -h|--help) sed -n 2,15p "$0"; exit 0 ;;
        -*)        echo "unknown option $1" >&2; exit 1 ;;
        *)         GATES+=("$1"); shift ;;
    esac
done

command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }
[ -f "$STATE" ] || { echo "no $STATE; run from the project root" >&2; exit 1; }
[ -n "$REASON" ] || { echo "--reason is required" >&2; exit 1; }
[ "${#GATES[@]}" -gt 0 ] || { echo "name at least one gate" >&2; exit 1; }

for g in "${GATES[@]}"; do
    jq -e --arg g "$g" '.passed_gates // [] | index($g)' "$STATE" >/dev/null \
        || { echo "gate $g is not passed; nothing to reopen" >&2; exit 1; }
done

WHO="$(git config user.name 2>/dev/null || echo "${USER:-unknown}")"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
GATES_JSON="$(printf '%s\n' "${GATES[@]}" | jq -R . | jq -s .)"

NEW="$(jq --argjson gs "$GATES_JSON" --arg why "$REASON" --arg by "$WHO" --arg at "$NOW" '
    .passed_gates = ((.passed_gates // []) - $gs)
    | .approval_history = ((.approval_history // []) + [
        $gs[] as $g | select(.approvals[$g] != null)
        | {gate: $g, approval: .approvals[$g], superseded_at: $at}])
    | .approvals = ((.approvals // {}) | with_entries(select(.key as $k | $gs | index($k) | not)))
    | .reopened = ((.reopened // []) + [{gates: $gs, reason: $why, by: $by, at: $at}])
' "$STATE")"

echo "Reopening: ${GATES[*]}"
echo "Reason:    $REASON"
echo "Remaining passed gates: $(echo "$NEW" | jq -r '.passed_gates | join(", ")')"
if [ "$DRY" -eq 1 ]; then
    echo "[dry-run] no changes written"
    exit 0
fi
printf '%s\n' "$NEW" > "$STATE"
echo "Updated $STATE. Commit it, then re-run the gate checks and re-approve."
