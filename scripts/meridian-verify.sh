#!/bin/bash
# meridian-verify.sh
# Meridian Portable Verifier (Gate 5.2) — the platform-neutral enforcement boundary.
#
# Claude Code can block at the keystroke boundary (PreToolUse exit 2). Every other
# platform cannot — so Meridian relocates enforcement to the git/CI boundary, which
# every platform shares. This script is that boundary: a single command that runs
# the same engines the Tier-1 hooks use, exits non-zero on any blocking failure, and
# is wired into a pre-commit hook and a CI workflow by install.sh (all tiers).
#
# It does NOT depend on Claude Code. Run it by hand, from a git pre-commit hook, or
# from CI — the result is identical.
#
# Checks (blocking unless noted):
#   1. gates.yaml structure + circular dependencies (if a gates.yaml exists)
#   2. memory schema validity (all present memory files)
#   3. standing evaluator verdicts (a FAIL / sub-threshold verdict blocks)
#   4. drift sensor (ADVISORY by default; set MERIDIAN_DRIFT_BLOCK=1 to make it block)
#
# Usage:
#   meridian-verify.sh [project-dir] [--no-drift] [--quiet]
#   MERIDIAN_PROJECT_DIR=/path meridian-verify.sh
#
# Exit codes:
#   0 = all blocking checks passed (drift may have warned)
#   1 = at least one blocking check failed (commit/CI should be rejected)

set -uo pipefail

# ─── Config ──────────────────────────────────────────────────────────────────
PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-}"
NO_DRIFT=0
QUIET=0

for arg in "$@"; do
    case "$arg" in
        --no-drift) NO_DRIFT=1 ;;
        --quiet)    QUIET=1 ;;
        --help|-h)
            sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        -*) echo "Unknown option: $arg" >&2; exit 1 ;;
        *)  [ -z "$PROJECT_DIR" ] && PROJECT_DIR="$arg" ;;
    esac
done
PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MERIDIAN_DIR="$PROJECT_DIR/.meridian"
LOG_EVENT="$SCRIPT_DIR/log-event.sh"
THRESHOLD="${EVALUATOR_THRESHOLD:-7.0}"
DRIFT_BLOCK="${MERIDIAN_DRIFT_BLOCK:-0}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

FAILURES=()
WARNINGS=()

say()  { [ "$QUIET" -eq 1 ] || echo -e "$@"; }
okln() { say "${GREEN}✓${NC} $1"; }
failln() { say "${RED}✗${NC} $1"; FAILURES+=("$1"); }
warnln() { say "${YELLOW}!${NC} $1"; WARNINGS+=("$1"); }

telemetry() {
    [ -f "$LOG_EVENT" ] || return 0
    MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$LOG_EVENT" "$@" >/dev/null 2>&1 || true
}

# ─── 1. Gate DAG integrity ───────────────────────────────────────────────────
check_gates() {
    local gates_file="$MERIDIAN_DIR/gates.yaml"
    local engine="$SCRIPT_DIR/gate-engine.sh"
    if [ ! -f "$gates_file" ]; then
        say "  ℹ  no .meridian/gates.yaml — skipping gate DAG check"
        return 0
    fi
    if [ ! -f "$engine" ]; then
        failln "gate-engine.sh not found — cannot verify gate DAG"
        return 0
    fi
    if MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$engine" validate >/dev/null 2>&1; then
        okln "gates.yaml structure valid"
    else
        failln "gates.yaml failed structural validation"
    fi
    if MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$engine" check-circular >/dev/null 2>&1; then
        okln "no circular dependencies in gate DAG"
    else
        failln "circular dependency detected in gate DAG"
    fi
}

# ─── 1b. Gate state integrity ────────────────────────────────────────────────
# Every passed gate must exist, and every passed human_approval gate must carry
# an approval record. mark-passed writes both; a hand-edited state file won't.
check_gate_state() {
    local gates_file="$MERIDIAN_DIR/gates.yaml" state="$MERIDIAN_DIR/gate-state.json"
    [ -f "$gates_file" ] && [ -f "$state" ] || return 0
    if ! command -v jq >/dev/null 2>&1 || ! command -v yq >/dev/null 2>&1; then
        warnln "jq/yq not found — skipping gate state check"
        return 0
    fi
    local gate type bad=0
    for gate in $(jq -r '.passed_gates // [] | .[]' "$state" 2>/dev/null | tr -d '\r'); do
        type=$(yq eval ".gates[] | select(.id == \"$gate\") | .type" "$gates_file" 2>/dev/null | tr -d '\r')
        if [ -z "$type" ] || [ "$type" = "null" ]; then
            failln "gate-state lists '$gate' as passed but gates.yaml has no such gate"; bad=1
        elif [ "$type" = "human_approval" ] && ! jq -e --arg g "$gate" '.approvals[$g].by' "$state" >/dev/null 2>&1; then
            failln "human approval gate '$gate' is marked passed without an approval record (operator: gate-engine.sh mark-passed $gate --approve <token>)"; bad=1
        fi
    done
    [ "$bad" -eq 0 ] && okln "gate state consistent ($(jq '.passed_gates // [] | length' "$state") passed)"
    return 0
}

# ─── 2. Memory schema validity ───────────────────────────────────────────────
check_memory() {
    local validate="$SCRIPT_DIR/validate-memory.sh"
    local mem_dir="$MERIDIAN_DIR/memory"
    [ -d "$mem_dir" ] || { say "  ℹ  no memory directory — skipping memory check"; return 0; }
    [ -f "$validate" ] || { warnln "validate-memory.sh not found — skipping memory check"; return 0; }

    local pair type file any=0
    for pair in "semantic:semantic.json" "episodic:episodic.jsonl" "corrections:corrections.jsonl"; do
        type="${pair%%:*}"; file="$mem_dir/${pair##*:}"
        [ -f "$file" ] || continue
        any=1
        if MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$validate" "$type" "$file" >/dev/null 2>&1; then
            okln "$type memory valid"
        else
            failln "$type memory failed schema validation"
        fi
    done
    [ "$any" -eq 0 ] && say "  ℹ  no memory files yet — nothing to validate"
}

# ─── 3. Standing evaluator verdicts ──────────────────────────────────────────
# A gate that has a verdict file with verdict==fail or score<threshold is rejected
# work; committing over it should be blocked. Missing verdicts are not failures
# here (the verdict contract is enforced at gate-transition time by run-evaluator).
check_evaluator() {
    local eval_dir="$MERIDIAN_DIR/evaluator"
    [ -d "$eval_dir" ] || { say "  ℹ  no evaluator verdicts — skipping"; return 0; }
    command -v jq >/dev/null 2>&1 || { warnln "jq not found — skipping evaluator check"; return 0; }

    local f gate score verdict any=0
    for f in "$eval_dir"/*-verdict.json; do
        [ -f "$f" ] || continue
        any=1
        if ! jq empty "$f" >/dev/null 2>&1; then
            failln "evaluator verdict is not valid JSON: $(basename "$f")"
            continue
        fi
        gate=$(jq -r '.gate // "?"' "$f")
        score=$(jq -r '.score // 0' "$f")
        verdict=$(jq -r '.verdict // "?"' "$f")
        if [ "$verdict" = "fail" ]; then
            failln "gate '$gate' has a standing FAIL verdict (score $score)"
        elif awk -v s="$score" -v t="$THRESHOLD" 'BEGIN{exit !((s+0) < (t+0))}'; then
            failln "gate '$gate' verdict score $score is below threshold $THRESHOLD"
        else
            okln "gate '$gate' evaluator verdict: $verdict (score $score)"
        fi
    done
    [ "$any" -eq 0 ] && say "  ℹ  no evaluator verdict files — nothing to check"
}

# ─── 4. Drift sensor (advisory by default) ───────────────────────────────────
check_drift() {
    [ "$NO_DRIFT" -eq 1 ] && { say "  ℹ  drift check skipped (--no-drift)"; return 0; }
    local verdict="$MERIDIAN_DIR/drift/drift-verdict.json"
    [ -f "$verdict" ] || { say "  ℹ  no drift verdict — skipping (run /drift-check to generate)"; return 0; }
    command -v jq >/dev/null 2>&1 || { warnln "jq not found — skipping drift check"; return 0; }

    local score rec
    score=$(jq -r '.alignment_score // 0' "$verdict" 2>/dev/null)
    rec=$(jq -r '.recommendation // "unknown"' "$verdict" 2>/dev/null)
    telemetry drift_score alignment_score="$score" recommendation="$rec" || true

    if [ "$rec" = "drifted" ]; then
        if [ "$DRIFT_BLOCK" = "1" ]; then
            failln "drift detected (score $score/10, recommendation: drifted) — blocking (MERIDIAN_DRIFT_BLOCK=1)"
        else
            warnln "drift detected (score $score/10, recommendation: drifted) — advisory only (set MERIDIAN_DRIFT_BLOCK=1 to block)"
        fi
    elif [ "$rec" = "warn" ]; then
        warnln "alignment is slipping (score $score/10) — review divergences"
    else
        okln "no drift detected (score $score/10)"
    fi
}

# ─── Main ────────────────────────────────────────────────────────────────────
main() {
    say "${BLUE}━━━ Meridian Verify ━━━${NC}"
    say "Project: $PROJECT_DIR"
    say ""

    if [ ! -d "$MERIDIAN_DIR" ]; then
        echo -e "${RED}✗${NC} not a Meridian project (no .meridian/ at $PROJECT_DIR)" >&2
        exit 1
    fi

    say "${BLUE}Gate DAG${NC}";        check_gates; check_gate_state; say ""
    say "${BLUE}Memory${NC}";          check_memory;    say ""
    say "${BLUE}Evaluator${NC}";       check_evaluator; say ""
    say "${BLUE}Drift${NC}";           check_drift;     say ""

    local nf="${#FAILURES[@]}" nw="${#WARNINGS[@]}"
    say "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if [ "$nf" -gt 0 ]; then
        say "${RED}VERIFY FAILED${NC} — $nf blocking issue(s), $nw warning(s)"
        local x
        for x in "${FAILURES[@]}"; do say "  ${RED}✗${NC} $x"; done
        telemetry gate_blocked gate=verify reason="meridian-verify: $nf blocking issue(s)" || true
        exit 1
    else
        if [ "$nw" -gt 0 ]; then
            say "${GREEN}VERIFY PASSED${NC} — 0 blocking issues, $nw warning(s)"
        else
            say "${GREEN}VERIFY PASSED${NC} — all checks clean"
        fi
        telemetry tool_used tool=meridian-verify hook=verify outcome=passed || true
        exit 0
    fi
}

main
