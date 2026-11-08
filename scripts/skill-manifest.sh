#!/bin/bash
# skill-manifest.sh
# Meridian skill metadata layer (Gate 2.5 — progressive disclosure)
#
# Reads the YAML frontmatter from every skill doc in .claude/skills/ and emits
# the "always-loaded" metadata layer. This is the cheap index (name, trigger,
# purpose, declared tokens_metadata) that stays in context; the doc BODY is
# loaded only when the skill is invoked, and REFERENCES on demand.
#
# Usage:
#   skill-manifest.sh            # human-readable table (default)
#   skill-manifest.sh --json     # machine-readable array
#   skill-manifest.sh validate   # exit 2 if any skill is missing required keys
#
# Required frontmatter keys: name, trigger, purpose, type, load, tokens_metadata
#
# Exit codes: 0 = ok, 2 = validation failure

set -uo pipefail

PROJECT_DIR="${MERIDIAN_PROJECT_DIR:-$(pwd)}"
SKILLS_DIR="$PROJECT_DIR/.claude/skills"

BLUE='\033[0;34m'; GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'

REQUIRED_KEYS="name trigger purpose type load tokens_metadata"

# Extract the frontmatter block (between the first two --- fences), CRLF-safe.
frontmatter() {
    awk '
        { sub(/\r$/, "") }
        NR==1 && $0=="---" { infm=1; next }
        infm && $0=="---" { exit }
        infm { print }
    ' "$1"
}

# Read a flat "key: value" from a frontmatter block.
fm_get() {
    # $1 = frontmatter text, $2 = key
    printf '%s\n' "$1" | awk -v k="$2" '
        { sub(/\r$/, "") }
        $0 ~ "^"k":" { sub(/^[^:]*:[[:space:]]*/, ""); print; exit }
    '
}

# Approx body tokens: (total chars - frontmatter chars) / 4
body_tokens() {
    local file="$1" fm="$2" total fmchars
    total=$(wc -c < "$file" | tr -d ' ')
    fmchars=$(printf '%s' "$fm" | wc -c | tr -d ' ')
    awk -v t="$total" -v f="$fmchars" 'BEGIN{ b=t-f-8; if(b<0)b=0; printf "%d", b/4 }'
}

collect() {
    # Emit TSV: name<TAB>trigger<TAB>type<TAB>load<TAB>tokens_metadata<TAB>body_tokens<TAB>missing<TAB>purpose
    local file fm name trigger purpose type load tmeta btok missing key
    for file in "$SKILLS_DIR"/*/*.md; do
        [ -f "$file" ] || continue
        fm=$(frontmatter "$file")
        if [ -z "$fm" ]; then
            printf '%s\t\t\t\t\t\tNO-FRONTMATTER\t\n' "$(basename "$(dirname "$file")")"
            continue
        fi
        name=$(fm_get "$fm" name)
        trigger=$(fm_get "$fm" trigger)
        purpose=$(fm_get "$fm" purpose)
        type=$(fm_get "$fm" type)
        load=$(fm_get "$fm" load)
        tmeta=$(fm_get "$fm" tokens_metadata)
        btok=$(body_tokens "$file" "$fm")
        missing=""
        for key in $REQUIRED_KEYS; do
            [ -n "$(fm_get "$fm" "$key")" ] || missing="${missing:+$missing,}$key"
        done
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "${name:-?}" "${trigger:-?}" "${type:-?}" "${load:-?}" \
            "${tmeta:-?}" "$btok" "${missing:-ok}" "${purpose:-}"
    done
}

cmd_list() {
    echo -e "${BLUE}Meridian skill manifest (metadata layer)${NC}"
    echo ""
    printf "  %-16s %-18s %-13s %-9s %-9s %s\n" "SKILL" "TRIGGER" "TYPE" "META(t)" "BODY(t)" "PURPOSE"
    printf "  %-16s %-18s %-13s %-9s %-9s %s\n" "-----" "-------" "----" "-------" "-------" "-------"
    local sum_meta=0 sum_body=0 count=0
    while IFS=$'\t' read -r name trigger type load tmeta btok missing purpose; do
        printf "  %-16s %-18s %-13s %-9s %-9s %s\n" "$name" "$trigger" "$type" "$tmeta" "$btok" "${purpose:0:48}"
        [ "$tmeta" != "?" ] && sum_meta=$((sum_meta + tmeta))
        sum_body=$((sum_body + btok)); count=$((count + 1))
    done < <(collect)
    echo ""
    echo "  $count skills | always-loaded metadata ~${sum_meta}t | full bodies ~${sum_body}t"
    echo "  Progressive disclosure saves ~$((sum_body - sum_meta))t until a skill is invoked."
}

cmd_json() {
    collect | awk -F'\t' '
        BEGIN { print "[" ; first=1 }
        {
            if (!first) print ",";
            first=0;
            gsub(/"/, "\\\"", $8);
            printf "  {\"name\":\"%s\",\"trigger\":\"%s\",\"type\":\"%s\",\"load\":\"%s\",\"tokens_metadata\":%s,\"body_tokens\":%s,\"status\":\"%s\",\"purpose\":\"%s\"}",
                $1, $2, $3, $4, ($5=="?"?"null":$5), $6, $7, $8;
        }
        END { print ""; print "]" }
    '
}

cmd_validate() {
    local fails=0 name missing
    while IFS=$'\t' read -r name trigger type load tmeta btok missing purpose; do
        if [ "$missing" != "ok" ]; then
            echo -e "${RED}✗${NC} $name: missing frontmatter key(s): $missing" >&2
            fails=$((fails + 1))
        fi
    done < <(collect)
    if [ "$fails" -gt 0 ]; then
        echo -e "${RED}Skill manifest validation FAILED: $fails skill(s) incomplete${NC}" >&2
        exit 2
    fi
    echo -e "${GREEN}✓${NC} All skills have complete frontmatter"
}

main() {
    [ -d "$SKILLS_DIR" ] || { echo "No skills dir at $SKILLS_DIR" >&2; exit 1; }
    case "${1:-list}" in
        list)     cmd_list ;;
        --json)   cmd_json ;;
        validate) cmd_validate ;;
        *) echo "Usage: skill-manifest.sh [list|--json|validate]" >&2; exit 1 ;;
    esac
}

main "$@"
