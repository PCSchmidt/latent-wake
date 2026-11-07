#!/bin/bash
# dogfood.sh
# Meridian dogfood log: is the harness catching real problems, and at what cost?
#
# Three things telemetry alone cannot tell you, recorded by the operator:
#   1. Was each stop (a block by a hook or by meridian-verify) a real problem
#      or a false alarm?
#   2. Escapes: problems found AFTER a gate passed (what the checks missed).
#   3. Overhead: time spent on Meridian itself rather than the project.
#
# Stops come from .meridian/telemetry.jsonl (git-ignored, local). Labels,
# escapes, and overhead go to .meridian/dogfood.jsonl, which is meant to be
# COMMITTED: each label copies the stop's details, so the file stands alone as
# evidence even after telemetry is rotated.
#
# Usage:
#   dogfood.sh stops [--unlabeled]                     List stops with index numbers
#   dogfood.sh label <n> <real|false_alarm|unclear> [note...]
#   dogfood.sh escape "<what slipped through>" [--gate <id>] [--severity low|medium|high]
#   dogfood.sh overhead <hours> [note...]              Time spent on Meridian itself
#   dogfood.sh report [--md]                           Summary (plain or markdown)
#
# A stop is a `hook_blocked` event (every hook block) or a `gate_blocked`
# event from meridian-verify (gate=verify). gate-engine's own gate_blocked
# duplicates the hook_blocked of the pre-hook that failed, so it is not counted.

set -euo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-$(pwd)}"
TELEMETRY_FILE="$PROJECT_DIR/.meridian/telemetry.jsonl"
DOGFOOD_FILE="$PROJECT_DIR/.meridian/dogfood.jsonl"

die() { echo "dogfood: $*" >&2; exit 1; }
now() { date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%S"; }

command -v jq >/dev/null 2>&1 || die "jq is required"

# All stops from telemetry, oldest first, numbered from 1. Invalid lines are skipped.
telemetry_stops() {
    if [ ! -f "$TELEMETRY_FILE" ]; then
        echo '[]'
        return 0
    fi
    jq -c -R 'fromjson? // empty' "$TELEMETRY_FILE" | jq -s -c '
        [ .[]
          | select(.event_type == "hook_blocked"
                   or (.event_type == "gate_blocked" and (.gate | tostring) == "verify"))
          | { timestamp,
              session_id,
              source: (if .event_type == "hook_blocked" then "hook:\(.hook // "unknown")" else "verify" end),
              reason: ((.reason // "") | tostring | gsub("[\r\n\t]+"; " ")) } ]
        | to_entries | map(.value + { n: (.key + 1) })'
}

dogfood_records() {
    if [ ! -f "$DOGFOOD_FILE" ]; then
        echo '[]'
        return 0
    fi
    jq -c -R 'fromjson? // empty' "$DOGFOOD_FILE" | jq -s -c '.'
}

append() {
    mkdir -p "$(dirname "$DOGFOOD_FILE")"
    echo "$1" | jq -c '.' >> "$DOGFOOD_FILE"
}

cmd_stops() {
    local only_unlabeled=0
    [ "${1:-}" = "--unlabeled" ] && only_unlabeled=1
    local stops records
    stops=$(telemetry_stops)
    records=$(dogfood_records)
    jq -n -r --argjson stops "$stops" --argjson recs "$records" --argjson only "$only_unlabeled" '
        def key: "\(.timestamp)|\(.source)|\(.reason)";
        ([ $recs[] | select(.type == "label") ] | map({ key: (.stop | key), value: .label }) | from_entries) as $labels
        | if ($stops | length) == 0 then "No stops recorded yet."
          else
            $stops[]
            | . as $s
            | ($labels[$s | key] // "unlabeled") as $label
            | select($only == 0 or $label == "unlabeled")
            | "\($s.n)\t\($s.timestamp)\t\($s.source)\t[\($label)]\t\($s.reason)"
          end'
}

cmd_label() {
    local n="${1:-}" label="${2:-}"
    [ -n "$n" ] && [ -n "$label" ] || die "usage: label <n> <real|false_alarm|unclear> [note...]"
    shift 2
    case "$label" in real|false_alarm|unclear) ;; *) die "label must be real, false_alarm, or unclear" ;; esac
    [[ "$n" =~ ^[0-9]+$ ]] || die "<n> must be a stop number from 'dogfood.sh stops'"
    local stop
    stop=$(telemetry_stops | jq -c --argjson n "$n" '.[] | select(.n == $n) | del(.n)')
    [ -n "$stop" ] || die "no stop #$n (run 'dogfood.sh stops')"
    append "$(jq -n -c --arg at "$(now)" --argjson stop "$stop" --arg label "$label" --arg note "$*" \
        '{type: "label", recorded_at: $at, stop: $stop, label: $label, note: $note}')"
    echo "Labelled stop #$n as $label"
}

cmd_escape() {
    local desc="${1:-}"
    [ -n "$desc" ] || die "usage: escape \"<what slipped through>\" [--gate <id>] [--severity low|medium|high]"
    shift
    local gate="" severity="medium"
    while [ $# -gt 0 ]; do
        case "$1" in
            --gate) gate="${2:-}"; shift 2 ;;
            --severity) severity="${2:-}"; shift 2 ;;
            *) die "unknown option: $1" ;;
        esac
    done
    case "$severity" in low|medium|high) ;; *) die "severity must be low, medium, or high" ;; esac
    append "$(jq -n -c --arg at "$(now)" --arg d "$desc" --arg g "$gate" --arg s "$severity" \
        '{type: "escape", recorded_at: $at, description: $d, gate: (if $g == "" then null else $g end), severity: $s}')"
    echo "Recorded escape ($severity)"
}

cmd_overhead() {
    local hours="${1:-}"
    [[ "$hours" =~ ^[0-9]+(\.[0-9]+)?$ ]] || die "usage: overhead <hours> [note...]"
    shift
    append "$(jq -n -c --arg at "$(now)" --argjson h "$hours" --arg note "$*" \
        '{type: "overhead", recorded_at: $at, hours: $h, note: $note}')"
    echo "Recorded ${hours}h of Meridian overhead"
}

cmd_report() {
    local md=0
    [ "${1:-}" = "--md" ] && md=1
    local stops records verdicts sessions
    stops=$(telemetry_stops)
    records=$(dogfood_records)
    if [ -f "$TELEMETRY_FILE" ]; then
        verdicts=$(jq -c -R 'fromjson? // empty' "$TELEMETRY_FILE" | jq -s -c '[ .[] | select(.event_type == "evaluator_verdict") | .verdict ]')
        sessions=$(jq -c -R 'fromjson? // empty' "$TELEMETRY_FILE" | jq -s -c '[ .[] | .session_id | select(. != null and . != "00000000") ] | unique | length')
    else
        verdicts='[]'
        sessions=0
    fi
    jq -n -r --argjson stops "$stops" --argjson recs "$records" --argjson verdicts "$verdicts" \
        --argjson sessions "$sessions" --argjson md "$md" --arg project "$(basename "$PROJECT_DIR")" '
        def key: "\(.timestamp)|\(.source)|\(.reason)";
        def pct(a; b): if b == 0 then "n/a" else "\((a * 100 / b) | round)%" end;
        # Latest label per stop wins; labels stand alone even if telemetry was rotated.
        ([ $recs[] | select(.type == "label") ] | group_by(.stop | key) | map(last)) as $labels
        | ([ $labels[] | .stop | key ]) as $labelled_keys
        | ([ $stops[] | select((key) as $k | $labelled_keys | index($k) | not) ]) as $unlabelled
        | ([ $labels[] | select(.label == "real") ] | length) as $real
        | ([ $labels[] | select(.label == "false_alarm") ] | length) as $false
        | ([ $labels[] | select(.label == "unclear") ] | length) as $unclear
        | ($unlabelled | length) as $open
        | ([ $recs[] | select(.type == "escape") ]) as $escapes
        | ([ $recs[] | select(.type == "overhead") ]) as $overhead
        | ([ $overhead[] | .hours ] | add // 0) as $hours
        | ([ ($labels | map(.stop)), $unlabelled ] | add
            | group_by(.source) | map("\(.[0].source): \(length)")) as $by_source
        | ($real + $false + $unclear + $open) as $total
        | if $md == 1 then
            "# Meridian dogfood report: \($project)\n",
            "| Measure | Value |",
            "|---|---|",
            "| Sessions | \($sessions) |",
            "| Stops (blocks) | \($total) |",
            "| Labelled real / false alarm / unclear | \($real) / \($false) / \($unclear) |",
            "| Unlabelled | \($open) |",
            "| Precision (real ÷ real+false alarm) | \(pct($real; $real + $false)) |",
            "| Escapes (missed by the gates) | \($escapes | length) |",
            "| Evaluator verdicts pass / warn / fail | \([ $verdicts[] | select(. == "pass") ] | length) / \([ $verdicts[] | select(. == "warn") ] | length) / \([ $verdicts[] | select(. == "fail") ] | length) |",
            "| Overhead hours | \($hours) |",
            "",
            (if ($by_source | length) > 0 then "**Stops by source:** \($by_source | join(", "))\n" else empty end),
            (if ($escapes | length) > 0 then "## Escapes\n", ($escapes[] | "- [\(.severity)] \(.description)\(if .gate then " (gate: \(.gate))" else "" end)"), "" else empty end),
            (if ($labels | length) > 0 then "## Labelled stops\n", ($labels[] | "- **\(.label)** · \(.stop.source) · \(.stop.reason)\(if .note != "" then " — \(.note)" else "" end)") else empty end)
          else
            "Meridian dogfood report: \($project)",
            "  sessions:          \($sessions)",
            "  stops:             \($total)  (\($by_source | join(", ")))",
            "  real/false/unclear: \($real)/\($false)/\($unclear)   unlabelled: \($open)",
            "  precision:         \(pct($real; $real + $false))",
            "  escapes:           \($escapes | length)",
            "  evaluator verdicts: \(if ($verdicts | length) == 0 then "none" else ($verdicts | group_by(.) | map("\(.[0]) \(length)") | join(", ")) end)",
            "  overhead hours:    \($hours)",
            (if $open > 0 then "\n  \($open) stop(s) unlabelled. Run: dogfood.sh stops --unlabeled" else empty end)
          end'
}

usage() { sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; }

main() {
    local cmd="${1:-}"
    [ $# -gt 0 ] && shift
    case "$cmd" in
        stops)    cmd_stops "$@" ;;
        label)    cmd_label "$@" ;;
        escape)   cmd_escape "$@" ;;
        overhead) cmd_overhead "$@" ;;
        report)   cmd_report "$@" ;;
        -h|--help|"") usage ;;
        *) die "unknown command: $cmd (try --help)" ;;
    esac
}

main "$@"
