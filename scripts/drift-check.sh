#!/bin/bash
# drift-check.sh
# Meridian Continuous Drift Sensor (Gate 3.3)
#
# Detects goal drift between original CONTRACT/SPEC commitments and current
# implementation state. Advisory only — warns, never blocks.
#
# Pattern mirrors run-evaluator.sh:
#   --prepare       Assemble drift context (git diff, CONTRACT/SPEC excerpts,
#                   FEATURES snapshot) into .meridian/drift/drift-request.json.
#                   Invoke /drift-check skill to run the evaluator subagent.
#   --check         Read .meridian/drift/drift-verdict.json written by the
#                   drift-evaluator subagent. Log drift_score to telemetry.
#                   Output divergences. Always exits 0 (advisory, not blocking).
#   (no args)       --prepare if no verdict exists yet; else --check.
#
# Exit codes:
#   0 = always (advisory — drift detection warns, does not block)
#   1 = usage error only

set -euo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-$(pwd)}"
MERIDIAN_DIR="$PROJECT_DIR/.meridian"
DRIFT_DIR="$MERIDIAN_DIR/drift"
REQUEST_FILE="$DRIFT_DIR/drift-request.json"
VERDICT_FILE="$DRIFT_DIR/drift-verdict.json"
SESSION_FILE="$MERIDIAN_DIR/session.json"
LOG_EVENT="$PROJECT_DIR/scripts/log-event.sh"

YELLOW='\033[1;33m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

# ─── Helpers ─────────────────────────────────────────────────────────────────

get_session_id() {
    if [ -f "$SESSION_FILE" ] && command -v jq >/dev/null 2>&1; then
        jq -r '.session_id // "00000000"' "$SESSION_FILE" 2>/dev/null || echo "00000000"
    else
        date +%s | tail -c 9 | head -c 8 || echo "00000000"
    fi
}

read_excerpt() {
    local file="$1" max_lines="${2:-30}"
    [ -f "$file" ] || { echo "(not found)"; return 0; }
    head -n "$max_lines" "$file" | tr -d '\r'
}

git_summary() {
    if ! command -v git >/dev/null 2>&1; then
        echo "(git not available)"
        return
    fi
    # Last 10 commits: hash + subject + files changed
    git -C "$PROJECT_DIR" log --oneline -10 2>/dev/null || echo "(no git log)"
    echo "---"
    git -C "$PROJECT_DIR" diff --stat HEAD~5..HEAD 2>/dev/null | tail -5 || true
}

features_snapshot() {
    local features_file="$MERIDIAN_DIR/FEATURES.json"
    [ -f "$features_file" ] || { echo "(no FEATURES.json)"; return 0; }
    local total happy full
    total=$(jq 'length' "$features_file" 2>/dev/null | tr -d '\r' || echo 0)
    happy=$(jq '[.[] | select(.lifecycle.happy_path == true)] | length' "$features_file" 2>/dev/null | tr -d '\r' || echo 0)
    full=$(jq '[.[] | select(
        .lifecycle.happy_path == true and .lifecycle.integration == true and
        .lifecycle.edge_cases == true and .lifecycle.error_handling == true and
        .lifecycle.hardening == true
    )] | length' "$features_file" 2>/dev/null | tr -d '\r' || echo 0)
    if [ "$total" -gt 0 ]; then
        local happy_pct full_pct
        happy_pct=$(awk "BEGIN {printf \"%d\", $happy * 100 / $total}")
        full_pct=$(awk "BEGIN {printf \"%d\", $full  * 100 / $total}")
        echo "${happy_pct}% happy-path / ${full_pct}% full-lifecycle (${total} features)"
    else
        echo "0 features"
    fi
}

# ─── Prepare ─────────────────────────────────────────────────────────────────

prepare() {
    mkdir -p "$DRIFT_DIR"

    local session_id ts contract_excerpt spec_excerpt git_diff features_snap

    session_id=$(get_session_id)
    ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%S")
    contract_excerpt=$(read_excerpt "$PROJECT_DIR/CONTRACT.md" 40)
    spec_excerpt=$(read_excerpt "$PROJECT_DIR/SPEC.md" 40)
    git_diff=$(git_summary)
    features_snap=$(features_snapshot)

    if command -v jq >/dev/null 2>&1; then
        jq -n \
            --arg session_id  "$session_id" \
            --arg requested_at "$ts" \
            --arg contract_excerpt "$contract_excerpt" \
            --arg spec_excerpt "$spec_excerpt" \
            --arg git_diff_summary "$git_diff" \
            --arg features_snapshot "$features_snap" \
            --arg verdict_path "$VERDICT_FILE" \
            '{
                session_id:        $session_id,
                requested_at:      $requested_at,
                contract_excerpt:  $contract_excerpt,
                spec_excerpt:      $spec_excerpt,
                git_diff_summary:  $git_diff_summary,
                features_snapshot: $features_snapshot,
                verdict_path:      $verdict_path
            }' > "$REQUEST_FILE"
    else
        printf '{"session_id":"%s","requested_at":"%s","verdict_path":"%s"}\n' \
               "$session_id" "$ts" "$VERDICT_FILE" > "$REQUEST_FILE"
    fi

    echo ""
    echo -e "${BLUE}${BOLD}Drift check prepared.${NC}"
    echo ""
    echo "  Request:  $REQUEST_FILE"
    echo "  Verdict:  $VERDICT_FILE (written by drift-evaluator subagent)"
    echo ""
    echo -e "  Run ${BOLD}/drift-check${NC} to invoke the evaluator subagent."
    echo "  Then run: bash scripts/drift-check.sh --check"
    echo ""
}

# ─── Check ───────────────────────────────────────────────────────────────────

check() {
    if [ ! -f "$VERDICT_FILE" ]; then
        echo ""
        echo -e "${YELLOW}No drift verdict found.${NC}"
        echo "  Run: bash scripts/drift-check.sh --prepare"
        echo "  Then invoke the /drift-check skill to run the evaluator."
        echo ""
        exit 0
    fi

    if ! command -v jq >/dev/null 2>&1; then
        echo "Warning: jq not available — cannot parse verdict" >&2
        exit 0
    fi

    if ! jq empty "$VERDICT_FILE" >/dev/null 2>&1; then
        echo -e "${YELLOW}Warning: drift verdict is not valid JSON: $VERDICT_FILE${NC}" >&2
        exit 0
    fi

    local score recommendation summary divergence_count ts
    score=$(jq -r '.alignment_score // 0' "$VERDICT_FILE" | tr -d '\r')
    recommendation=$(jq -r '.recommendation // "unknown"' "$VERDICT_FILE" | tr -d '\r')
    summary=$(jq -r '.summary // ""' "$VERDICT_FILE" | tr -d '\r')
    divergence_count=$(jq '.divergences | length' "$VERDICT_FILE" 2>/dev/null | tr -d '\r' || echo 0)
    ts=$(jq -r '.timestamp // ""' "$VERDICT_FILE" | tr -d '\r')

    # Log drift_score event to telemetry (always, advisory)
    if [ -f "$LOG_EVENT" ]; then
        bash "$LOG_EVENT" drift_score \
            alignment_score="$score" \
            recommendation="$recommendation" \
            divergences="$divergence_count" \
            >/dev/null 2>&1 || true
    fi

    # Output
    echo ""
    echo -e "${BOLD}Drift Report${NC}  (${ts:-unknown})"
    echo "──────────────────────────────────────"

    local score_color="$GREEN"
    local score_int
    score_int=$(awk "BEGIN {printf \"%d\", $score + 0}")
    if [ "$score_int" -lt 5 ]; then
        score_color='\033[0;31m'  # red
    elif [ "$score_int" -lt 7 ]; then
        score_color="$YELLOW"
    fi

    printf "  Alignment score:  "
    echo -e "${score_color}${score}/10${NC}"
    printf "  Recommendation:   "

    case "$recommendation" in
        aligned)  echo -e "${GREEN}aligned${NC}" ;;
        warn)     echo -e "${YELLOW}warn${NC}" ;;
        drifted)  echo -e '\033[0;31m'"drifted"${NC} ;;
        *)        echo "$recommendation" ;;
    esac

    echo ""

    if [ "$divergence_count" -gt 0 ]; then
        echo -e "  ${BOLD}Divergences (${divergence_count}):${NC}"
        echo ""
        jq -r '.divergences[] |
            "  [\(.severity | ascii_upcase)] \(.type): \(.description)"
        ' "$VERDICT_FILE" 2>/dev/null | tr -d '\r'
        echo ""
    fi

    if [ -n "$summary" ]; then
        echo "  $summary"
        echo ""
    fi

    if [ "$recommendation" = "aligned" ] && [ "$divergence_count" -eq 0 ]; then
        echo -e "  ${GREEN}No drift detected.${NC}"
        echo ""
    elif [ "$recommendation" != "aligned" ]; then
        echo -e "  ${YELLOW}Advisory only — review divergences above. No gates blocked.${NC}"
        echo ""
    fi
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    local mode="${1:-auto}"

    case "$mode" in
        --prepare|prepare)
            prepare
            ;;
        --check|check)
            check
            ;;
        auto)
            if [ -f "$VERDICT_FILE" ]; then
                check
            else
                prepare
            fi
            ;;
        --help|-h)
            echo "Usage: drift-check.sh [--prepare|--check]"
            echo ""
            echo "  --prepare   Assemble drift context; prompt operator to run /drift-check"
            echo "  --check     Read drift-verdict.json; log to telemetry; output divergences"
            echo "  (no args)   --prepare if no verdict exists, else --check"
            ;;
        *)
            echo "Usage: drift-check.sh [--prepare|--check]" >&2
            exit 1
            ;;
    esac
}

main "$@"
