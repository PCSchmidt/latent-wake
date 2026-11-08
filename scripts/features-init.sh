#!/bin/bash
# features-init.sh
# Seeds .meridian/FEATURES.json from SPEC.md ## and ### headings.
# All lifecycle sub-states start as false.
#
# Usage:
#   features-init.sh                    # init from $PROJECT_DIR/SPEC.md
#   features-init.sh --spec <path>      # use a different spec file
#   features-init.sh --force            # overwrite existing FEATURES.json

set -euo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-$(pwd)}"
MERIDIAN_DIR="$PROJECT_DIR/.meridian"
FEATURES_FILE="$MERIDIAN_DIR/FEATURES.json"
SPEC_FILE="$PROJECT_DIR/SPEC.md"
FORCE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --spec)  SPEC_FILE="$2"; shift 2 ;;
        --force) FORCE=1; shift ;;
        *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
    esac
done

if [ ! -f "$SPEC_FILE" ]; then
    echo "ERROR: Spec file not found: $SPEC_FILE" >&2
    echo "  Create SPEC.md or pass --spec <path>." >&2
    exit 1
fi

if [ -f "$FEATURES_FILE" ] && [ "$FORCE" -eq 0 ]; then
    echo "FEATURES.json already exists. Use --force to overwrite." >&2
    exit 1
fi

mkdir -p "$MERIDIAN_DIR"

# Extract ## and ### headings, strip hashes, skip known meta-sections.
# jq -R -s converts raw lines to a JSON array, then maps to feature objects.
features_json=$(
    grep -E '^#{2,3} ' "$SPEC_FILE" 2>/dev/null \
    | sed 's/^## //; s/^### //' \
    | jq -R -s '
        split("\n") |
        map(select(length > 0)) |
        map(select(
            . != "Overview" and . != "Purpose" and . != "Goals" and
            . != "Non-Goals" and . != "Out of Scope" and . != "References" and
            . != "Appendix" and . != "Changelog" and . != "Table of Contents" and
            . != "Feature List" and . != "Features" and . != "Feature Overview"
        )) |
        map({
            id: (
                . | ascii_downcase
                  | gsub("[^a-z0-9 -]"; "")
                  | gsub(" +"; "-")
                  | ltrimstr("-") | rtrimstr("-")
            ),
            name: .,
            source_section: .,
            lifecycle: {
                happy_path:     false,
                integration:    false,
                edge_cases:     false,
                error_handling: false,
                hardening:      false
            }
        })
    ' \
    || echo "[]"
)

feature_count=$(echo "$features_json" | jq 'length' | tr -d '\r')

if [ "$feature_count" -eq 0 ]; then
    echo "WARNING: No features found in $SPEC_FILE" >&2
    echo "  Add ## or ### headings to mark feature sections." >&2
fi

echo "$features_json" > "$FEATURES_FILE"
echo "✓ FEATURES.json initialized: $feature_count features (all lifecycle states: false)"
echo "  File: $FEATURES_FILE"
