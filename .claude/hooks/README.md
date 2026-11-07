# Meridian Hook System

Enforcement layer for the Meridian agent harness. Hooks fire automatically on
tool events in Claude Code and validate operations, enforce gates, and log telemetry.

---

## Architecture

Hooks are bash scripts registered in `.claude/settings.json`:

- **SessionStart.sh** — fires at conversation start; calls `session.sh start` and writes a `session_start` episodic event
- **PreToolUse.sh** — fires BEFORE tool execution; can block with exit code 2
- **PostToolUse.sh** — fires AFTER tool execution; validates memory writes + logs telemetry
- **hook-wrapper.sh** — common library (logging, timing, `parse_tool_use`); **sourced, never executed**

Registration in `.claude/settings.json` is required — Claude Code does not
auto-discover hooks. `install.sh` creates this file automatically.

---

## The hook-wrapper contract

**`hook-wrapper.sh` must be sourced, not executed directly.** Every hook starts with:

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/hook-wrapper.sh"
HOOK_NAME="my-hook"
```

The wrapper provides:

| Function | Purpose |
| -------- | ------- |
| `info "msg"` | log INFO to `.meridian/hooks.log` + stderr |
| `warn "msg"` | log WARN |
| `block "msg"` | log BLOCK + `exit 2` (prevents tool execution) |
| `error "msg"` | log ERROR + `exit 1` |
| `parse_tool_use` | parse stdin JSON into `$TOOL_NAME`, `$FILE_PATH`, `$COMMAND`, `$CONTENT`, `$TOOL_ARGS` |
| `timer_start` / `timer_end` | execution timing |

Environment variables set by `parse_tool_use`:

| Variable | Content |
| -------- | ------- |
| `$TOOL_NAME` | tool being executed (Read, Edit, Write, Bash, …) |
| `$FILE_PATH` | file path for Read/Edit/Write |
| `$COMMAND` | command string for Bash |
| `$CONTENT` | written text for Write/Edit (content-target scanning) |
| `$TOOL_ARGS` | full JSON tool_input |

---

## Exit codes

| Code | Meaning |
| ---- | ------- |
| `0` | allow / success |
| `1` | warn or recoverable error (allowed, logged) |
| `2` | **block** — prevent the tool call |

---

## Hook inventory

| Hook | Event | Role |
| ---- | ----- | ---- |
| `SessionStart.sh` | SessionStart | start session, write episodic event |
| `PreToolUse.sh` | PreToolUse | run `block-dangerous.sh`; exit 2 blocks |
| `PostToolUse.sh` | PostToolUse | validate memory writes, log telemetry |
| `block-dangerous.sh` | (subprocess of PreToolUse) | scan command/content vs `security-rules.yaml` |
| `validate-contract.sh` | gate pre-hook | structural check on CONTRACT.md |
| `validate-spec.sh` | gate pre-hook | structural check on SPEC.md |
| `validate-roadmap.sh` | gate pre-hook | surface check on ROADMAP.md |
| `run-tests.sh` | gate pre-hook | auto-detect + run tests; exit 2 on regression |
| `run-evaluator.sh` | gate verify | enforce evaluator verdict contract (A003) |

---

## Hook logs

```text
.meridian/hooks.log
```

Every hook writes timestamped entries:

```text
2026-06-01T18:00:00Z [INFO] [PreToolUse] Tool: Edit
2026-06-01T18:00:00Z [INFO] [PreToolUse] Tool execution allowed
2026-06-01T18:00:05Z [INFO] [PostToolUse] Memory validation passed: corrections
```

---

## Writing a new hook

```bash
#!/bin/bash
# my-hook.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/hook-wrapper.sh"
HOOK_NAME="my-hook"

main() {
    parse_tool_use
    info "Tool: ${TOOL_NAME:-unknown}"
    # validation logic...
    timer_end
    exit 0
}

main "$@"
```

Then register it in `.claude/settings.json` under the appropriate event key.
