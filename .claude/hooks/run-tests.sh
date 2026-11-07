#!/bin/bash
# run-tests.sh
# Meridian gate-transition validator (Gate 2.2)
#
# Auto-detects the project's test runner and executes it. Used as a `hooks.pre`
# entry on an `automated` gate (e.g. `tests_passing`) so the gate cannot clear
# while tests fail. This is mechanical anti-hallucination: the model cannot
# convince a bash script that failing tests pass.
#
# Detection order (first match wins):
#   1. TEST_CMD env override        -> run it verbatim
#   2. tests/test-*.sh              -> Meridian-style bash suites
#   3. pytest (pyproject/pytest.ini/setup.py/tests/*.py)
#   4. Cargo.toml                   -> cargo test
#   5. go.mod                       -> go test ./...
#   6. package.json "test" script   -> npm test
#   7. Makefile `test:` target      -> make test
#
# Usage:
#   run-tests.sh [dir]      # default: $PROJECT_DIR (or RUN_TESTS_DIR)
#
# Exit codes:
#   0 = tests passed (or no runner found -> warn, non-blocking)
#   2 = tests failed (block gate transition)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/hook-wrapper.sh"
HOOK_NAME="run-tests"

TARGET_DIR="${1:-${RUN_TESTS_DIR:-$PROJECT_DIR}}"

# Run a command in TARGET_DIR; block on non-zero exit.
run_or_block() {
    local label="$1"; shift
    info "Running tests via: $label"
    if ( cd "$TARGET_DIR" && "$@" ); then
        info "Tests passed ($label)"
        timer_end
        exit 0
    else
        block "Tests FAILED ($label) - gate cannot pass with failing tests"
    fi
}

main() {
    if [ ! -d "$TARGET_DIR" ]; then
        block "Test directory not found: $TARGET_DIR"
    fi

    # 1. Explicit override
    if [ -n "${TEST_CMD:-}" ]; then
        info "Running tests via: \$TEST_CMD"
        if ( cd "$TARGET_DIR" && eval "$TEST_CMD" ); then
            info "Tests passed (TEST_CMD)"; timer_end; exit 0
        else
            block "Tests FAILED (TEST_CMD) - gate cannot pass with failing tests"
        fi
    fi

    # 2. Meridian-style bash suites
    local suites=()
    while IFS= read -r f; do
        [ -n "$f" ] && suites+=("$f")
    done < <(find "$TARGET_DIR/tests" -maxdepth 1 -name 'test-*.sh' 2>/dev/null | sort)
    if [ "${#suites[@]}" -gt 0 ]; then
        info "Running ${#suites[@]} bash test suite(s) in tests/"
        local BASELINE="$TARGET_DIR/.meridian/test-baseline.txt"
        local failed=0 regressions=0 new_reds=0 s
        local -a passed_names=()
        for s in "${suites[@]}"; do
            local name; name=$(basename "$s")
            if bash "$s" >/dev/null 2>&1; then
                info "  PASS $name"
                passed_names+=("$name")
            else
                warn "  FAIL $name"
                failed=$((failed + 1))
                # Regression = suite was passing in the last all-green run
                if [ -f "$BASELINE" ] && grep -qx "$name" "$BASELINE" 2>/dev/null; then
                    regressions=$((regressions + 1))
                    warn "  ↳ REGRESSION: $name was passing — fix before proceeding"
                else
                    new_reds=$((new_reds + 1))
                    warn "  ↳ TDD red phase: $name is new — write implementation to make it green"
                fi
            fi
        done
        if [ "$failed" -gt 0 ]; then
            if [ "$regressions" -gt 0 ]; then
                block "$regressions regression(s) in ${#suites[@]} suite(s) — previously-passing suite(s) now FAILED"
            else
                # Only new-red tests failing (TDD red phase) — warn but allow
                warn "$new_reds new-red suite(s) in TDD red phase — implement to make green"
                timer_end
                exit 0
            fi
        fi
        # All-green: update baseline so future runs know what was passing
        if [ -d "$TARGET_DIR/.meridian" ]; then
            printf '%s\n' "${passed_names[@]}" > "$BASELINE"
            info "Test baseline updated (${#passed_names[@]} suites)"
        fi
        info "All ${#suites[@]} bash test suite(s) passed"; timer_end; exit 0
    fi

    # 3. pytest
    if [ -f "$TARGET_DIR/pyproject.toml" ] || [ -f "$TARGET_DIR/pytest.ini" ] || \
       [ -f "$TARGET_DIR/setup.py" ] || ls "$TARGET_DIR"/tests/*.py >/dev/null 2>&1; then
        if command -v pytest >/dev/null 2>&1; then
            run_or_block "pytest" pytest -q
        else
            warn "Python project detected but pytest not installed - skipping"
        fi
    fi

    # 4. Rust
    if [ -f "$TARGET_DIR/Cargo.toml" ] && command -v cargo >/dev/null 2>&1; then
        run_or_block "cargo test" cargo test
    fi

    # 5. Go
    if [ -f "$TARGET_DIR/go.mod" ] && command -v go >/dev/null 2>&1; then
        run_or_block "go test" go test ./...
    fi

    # 6. Node
    if [ -f "$TARGET_DIR/package.json" ] && command -v npm >/dev/null 2>&1; then
        if grep -qE '"test"[[:space:]]*:' "$TARGET_DIR/package.json" && \
           ! grep -qE '"test"[[:space:]]*:[[:space:]]*"[^"]*no test specified' "$TARGET_DIR/package.json"; then
            run_or_block "npm test" npm test --silent
        fi
    fi

    # 7. Makefile
    if [ -f "$TARGET_DIR/Makefile" ] && grep -qE '^test:' "$TARGET_DIR/Makefile"; then
        run_or_block "make test" make test
    fi

    warn "No test runner detected in $TARGET_DIR - nothing to run (configure TEST_CMD to enforce)"
    timer_end
    exit 0
}

main "$@"
