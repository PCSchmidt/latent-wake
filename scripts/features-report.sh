#!/bin/bash
# features-report.sh
# Lifecycle-weighted completion report.
# Reports two distinct numbers: happy-path % vs full-lifecycle %.
# A feature is "full-lifecycle complete" only when all five sub-states are true.
#
# Usage:
#   features-report.sh             # full breakdown
#   features-report.sh --short     # one-line "X% happy-path / Y% full-lifecycle"
#   features-report.sh --json      # machine-readable JSON

set -euo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-$(pwd)}"
FEATURES_FILE="${FEATURES_FILE_PATH:-$PROJECT_DIR/.meridian/FEATURES.json}"

if [ ! -f "$FEATURES_FILE" ]; then
    echo "No FEATURES.json found. Run: bash scripts/features-init.sh" >&2
    exit 1
fi

stats=$(jq -c '{
    total:          length,
    happy_path:     [.[] | select(.lifecycle.happy_path     == true)] | length,
    integration:    [.[] | select(.lifecycle.integration    == true)] | length,
    edge_cases:     [.[] | select(.lifecycle.edge_cases     == true)] | length,
    error_handling: [.[] | select(.lifecycle.error_handling == true)] | length,
    hardening:      [.[] | select(.lifecycle.hardening      == true)] | length,
    full_lifecycle: [.[] | select(
        .lifecycle.happy_path     == true and
        .lifecycle.integration    == true and
        .lifecycle.edge_cases     == true and
        .lifecycle.error_handling == true and
        .lifecycle.hardening      == true
    )] | length
}' "$FEATURES_FILE" | tr -d '\r')

total=$(echo "$stats" | jq '.total'          | tr -d '\r')
happy=$(echo "$stats" | jq '.happy_path'     | tr -d '\r')
full=$( echo "$stats" | jq '.full_lifecycle' | tr -d '\r')

if [ "$total" -eq 0 ]; then
    echo "No features in FEATURES.json. Run: bash scripts/features-init.sh" >&2
    exit 1
fi

happy_pct=$(awk "BEGIN {printf \"%d\", $happy * 100 / $total}")
full_pct=$( awk "BEGIN {printf \"%d\", $full  * 100 / $total}")

case "${1:---full}" in

    --json|json)
        integration=$(echo "$stats" | jq '.integration'    | tr -d '\r')
        edge_cases=$( echo "$stats" | jq '.edge_cases'     | tr -d '\r')
        err_hand=$(   echo "$stats" | jq '.error_handling' | tr -d '\r')
        hardening=$(  echo "$stats" | jq '.hardening'      | tr -d '\r')
        jq -n \
            --argjson total               "$total" \
            --argjson happy_path_count    "$happy" \
            --argjson full_lifecycle_count "$full" \
            --argjson happy_path_pct      "$happy_pct" \
            --argjson full_lifecycle_pct  "$full_pct" \
            --argjson integration         "$integration" \
            --argjson edge_cases          "$edge_cases" \
            --argjson error_handling      "$err_hand" \
            --argjson hardening           "$hardening" \
            '{
                total_features:         $total,
                happy_path_count:       $happy_path_count,
                full_lifecycle_count:   $full_lifecycle_count,
                happy_path_pct:         $happy_path_pct,
                full_lifecycle_pct:     $full_lifecycle_pct,
                per_state: {
                    happy_path:     $happy_path_count,
                    integration:    $integration,
                    edge_cases:     $edge_cases,
                    error_handling: $error_handling,
                    hardening:      $hardening
                }
            }'
        ;;

    --short|short)
        echo "${happy_pct}% happy-path / ${full_pct}% full-lifecycle"
        ;;

    --full|full)
        integration=$(echo "$stats" | jq '.integration'    | tr -d '\r')
        edge_cases=$( echo "$stats" | jq '.edge_cases'     | tr -d '\r')
        err_hand=$(   echo "$stats" | jq '.error_handling' | tr -d '\r')
        hardening=$(  echo "$stats" | jq '.hardening'      | tr -d '\r')

        echo ""
        echo "Feature Lifecycle Completion"
        echo "──────────────────────────────────────"
        printf "  Happy-path complete:     %3d%%  (%d/%d features)\n" \
            "$happy_pct" "$happy" "$total"
        printf "  Full-lifecycle complete: %3d%%  (%d/%d features)\n" \
            "$full_pct" "$full" "$total"
        echo ""
        echo "  Per-state breakdown:"
        printf "    %-20s %d/%d\n" "happy_path:"     "$happy"       "$total"
        printf "    %-20s %d/%d\n" "integration:"    "$integration" "$total"
        printf "    %-20s %d/%d\n" "edge_cases:"     "$edge_cases"  "$total"
        printf "    %-20s %d/%d\n" "error_handling:" "$err_hand"    "$total"
        printf "    %-20s %d/%d\n" "hardening:"      "$hardening"   "$total"
        echo ""
        ;;

    *)
        echo "Usage: features-report.sh [--full|--short|--json]" >&2
        exit 1
        ;;
esac
