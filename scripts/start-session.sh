#!/bin/bash
# start-session.sh
# Meridian session bootstrap (Gate 2.4 — backs the /start skill)
#
# One command to begin (or resume) a work session: ensures a session exists,
# surfaces "where am I?" (current gate, completed gates, calibration), and runs
# a fast memory sanity check. Read this at the top of every session instead of
# manually stitching session.sh + status-report.sh + gate-engine together.
#
# Usage:
#   start-session.sh            # resume if a session exists, else start one
#   start-session.sh --new      # force a fresh session
#   start-session.sh --project <name>
#
# Exit codes: 0 = ok, non-zero = error

set -euo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-$(pwd)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION_FILE="$PROJECT_DIR/.meridian/session.json"

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${BLUE}$1${NC}"; }
success() { echo -e "${GREEN}✓${NC} $1"; }

FORCE_NEW=0; PROJECT_ARG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --new)     FORCE_NEW=1; shift ;;
        --project) PROJECT_ARG="${2:-}"; shift 2 ;;
        -h|--help) echo "Usage: start-session.sh [--new] [--project <name>]"; exit 0 ;;
        *)         echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Meridian — session start"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. Session: resume or start
if [ -f "$SESSION_FILE" ] && [ "$FORCE_NEW" -eq 0 ]; then
    local_id=$(jq -r '.session_id // "unknown"' "$SESSION_FILE" 2>/dev/null || echo "unknown")
    success "Resuming session $local_id"
else
    if [ -f "$SCRIPT_DIR/session.sh" ]; then
        if [ -n "$PROJECT_ARG" ]; then
            MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$SCRIPT_DIR/session.sh" start "project=$PROJECT_ARG"
        else
            MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$SCRIPT_DIR/session.sh" start
        fi
    fi
fi

# 2. Where am I? (compact status)
echo ""
if [ -f "$SCRIPT_DIR/status-report.sh" ]; then
    MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$SCRIPT_DIR/status-report.sh" full 2>/dev/null || true
fi

# 3. Current gate + what it needs
echo ""
if [ -f "$SCRIPT_DIR/gate-engine.sh" ] && [ -f "$PROJECT_DIR/.meridian/gates.yaml" ]; then
    cur=$(MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$SCRIPT_DIR/gate-engine.sh" current 2>/dev/null || echo "unknown")
    info "Current gate: $cur"
else
    info "No gates.yaml — running without a gate DAG (gate enforcement inactive)"
fi

# 4. Fast memory sanity check (non-fatal)
echo ""
if [ -f "$SCRIPT_DIR/memory-doctor.sh" ]; then
    if MERIDIAN_PROJECT_DIR="$PROJECT_DIR" bash "$SCRIPT_DIR/memory-doctor.sh" >/dev/null 2>&1; then
        success "Memory check: OK"
    else
        echo -e "${YELLOW}!${NC} Memory check reported issues — run /memory doctor for detail"
    fi
fi

echo ""
success "Ready. Pick up the current gate or tell me what's on your head."
