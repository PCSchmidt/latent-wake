---
name: testing
trigger: /testing
purpose: Run the project tests and surface gate test and evaluation status
type: wired
backing: .claude/hooks/run-tests.sh
load: on-invocation
tokens_metadata: 65
references: .claude/hooks/run-tests.sh, .claude/hooks/run-evaluator.sh
---

# Testing Skill

**Skill:** testing
**Trigger:** `/testing`
**Purpose:** Run the project's tests and surface the gate's test/evaluation status

---

## Commands

### `/testing run`

Auto-detect the test runner and run it. Blocks (exit 2) on failure — the same
script a `tests_passing` gate uses as a `hooks.pre` entry.

```bash
bash "$PROJECT_DIR/.claude/hooks/run-tests.sh"
```

Detection order: `TEST_CMD` override → Meridian bash suites (`tests/test-*.sh`)
→ pytest → cargo → go → npm → make.

### `/testing evaluate <gate>`

Check the independent evaluator verdict for a gate (generator-evaluator
separation, A003). Blocks unless a verdict file clears `verdict==pass` and
`score >= EVALUATOR_THRESHOLD` (default 7.0).

```bash
bash "$PROJECT_DIR/.claude/hooks/run-evaluator.sh" --check <gate>
```

### `/testing prepare-eval <gate> [artifacts...]`

Write the evaluator request payload for a separate evaluator subagent to consume.

```bash
bash "$PROJECT_DIR/.claude/hooks/run-evaluator.sh" --prepare <gate> <artifacts...>
```

---

## How tests gate progress

`run-tests.sh` is the mechanical anti-hallucination control: the model cannot
declare "tests passing" — a gate with `run-tests.sh` in its `hooks.pre` stays
blocked until the runner actually exits 0. Meridian itself currently has eight
bash suites under `tests/`.

For the test-authoring methodology (write tests from the spec, not the
implementation; avoid tautological tests), this skill defers to the project's
own testing conventions — Meridian does not prescribe a framework, only that
tests exist and pass before the gate clears.

---

**Status:** Complete (Gate 2.4) — wraps `run-tests.sh` and `run-evaluator.sh`
from Gate 2.2
