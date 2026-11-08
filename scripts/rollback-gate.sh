#!/bin/bash
# rollback-gate.sh
# Meridian gate rollback (Gate 2.4 — backs the /rollback skill)
#
# Reverts the gate STATE (.meridian/gate-state.json) to an earlier point: either
# the single most-recent passed gate, or back to a named gate. It does NOT touch
# code — it prints git guidance so you can revert the corresponding commit
# yourself (gate state and source history are deliberately separate).
#
# Usage:
#   rollback-gate.sh --list             # show passed gates
#   rollback-gate.sh                    # remove the most-recent passed gate
#   rollback-gate.sh --to <gate>        # keep <gate>, remove everything after it
#   rollback-gate.sh [--to <gate>] --dry-run
#
# Exit codes: 0 = ok, non-zero = error
#
# Note: gate IDs are stored sorted (mark-passed uses `unique`), so "most recent"
# means the lexically-highest gate id (1.1 < 1.2 < 2.1 < 2.2 ...).

set -euo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-$(pwd)}"
STATE_FILE="$PROJECT_DIR/.meridian/gate-state.json"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
error()   { echo -e "${RED}ERROR:${NC} $1" >&2; exit "${2:-1}"; }
success() { echo -e "${GREEN}✓${NC} $1"; }
info()    { echo -e "${BLUE}$1${NC}"; }

command -v jq >/dev/null 2>&1 || error "jq is required for rollback"

TO_GATE=""; DRY_RUN=0; LIST=0
while [ $# -gt 0 ]; do
    case "$1" in
        --to)      TO_GATE="${2:-}"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        --list)    LIST=1; shift ;;
        -h|--help) echo "Usage: rollback-gate.sh [--list] [--to <gate>] [--dry-run]"; exit 0 ;;
        *)         error "Unknown argument: $1" ;;
    esac
done

[ -f "$STATE_FILE" ] || error "No gate-state.json at $STATE_FILE — nothing to roll back"

PASSED=$(jq -r '.passed_gates // [] | .[]' "$STATE_FILE" 2>/dev/null || true)
if [ -z "$PASSED" ]; then
    info "No passed gates recorded — nothing to roll back"
    exit 0
fi

if [ "$LIST" -eq 1 ]; then
    info "Passed gates:"
    echo "$PASSED" | sed 's/^/  /'
    exit 0
fi

# Compute the new passed set and which gate(s) are being removed.
if [ -n "$TO_GATE" ]; then
    # Keep gates <= TO_GATE; the target must exist.
    echo "$PASSED" | grep -qx "$TO_GATE" || error "Gate '$TO_GATE' is not in the passed set (see --list)"
    NEW=$(jq -c --arg g "$TO_GATE" '.passed_gates | map(select(. <= $g))' "$STATE_FILE")
    REMOVED=$(jq -r --arg g "$TO_GATE" '.passed_gates | map(select(. > $g)) | .[]' "$STATE_FILE")
    TARGET_DESC="back to gate $TO_GATE"
else
    # Remove the single highest gate.
    LAST=$(echo "$PASSED" | sort | tail -1)
    NEW=$(jq -c --arg g "$LAST" '.passed_gates | map(select(. != $g))' "$STATE_FILE")
    REMOVED="$LAST"
    TARGET_DESC="removing most-recent gate $LAST"
fi

if [ -z "${REMOVED// }" ]; then
    info "Nothing to remove ($TARGET_DESC) — state already at or before that point"
    exit 0
fi

echo ""
info "Rollback plan ($TARGET_DESC):"
echo "  removing:"
echo "$REMOVED" | sed 's/^/    - /'
echo "  remaining passed gates: $(echo "$NEW" | jq -r 'join(", ")')"

if [ "$DRY_RUN" -eq 1 ]; then
    echo ""
    info "[dry-run] no changes written"
    exit 0
fi

# Back up and write new state
cp "$STATE_FILE" "${STATE_FILE}.bak"
tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT
jq --argjson new "$NEW" '.passed_gates = $new' "$STATE_FILE" > "$tmp"
mv "$tmp" "$STATE_FILE"

success "Gate state rolled back ($TARGET_DESC)"
success "Backup: ${STATE_FILE}.bak"

echo ""
echo -e "${YELLOW}Code is not reverted.${NC} To revert the source to the matching commit:"
echo "  git log --oneline --grep='Gate' | head     # find the gate's commit"
echo "  git revert <commit>        # safe: keeps history"
echo "  git reset --hard <commit>  # destructive: discards work after it"
