---
name: evaluate
trigger: /evaluate
purpose: Run an independent gate evaluation and write the verdict that gates require
type: wired
backing: .claude/agents/gate-evaluator.md
load: on-invocation
tokens_metadata: 70
references: .claude/agents/gate-evaluator.md, .claude/hooks/run-evaluator.sh, .meridian/evaluator/
---

# Evaluate Skill

**Trigger:** `/evaluate`

## What it does

Runs the Gate Evaluator — a **separate subagent** that reviews gate artifacts
it did not produce, scores them across four dimensions, and writes a verdict
file that `run-evaluator.sh --check` enforces.

This is the producer side of the generator-evaluator separation (A003).
`run-evaluator.sh` owns the contract; this skill owns invocation.

---

## Usage

### `/evaluate <gate>`

Evaluate all artifacts for the named gate using the request file prepared by
`run-evaluator.sh --prepare`.

**Steps this skill performs:**

1. Read `.meridian/evaluator/<gate>-request.json` — confirms a prepare step ran
2. Read each artifact listed in the request (CONTRACT.md, SPEC.md, gate exit
   artifacts, etc.)
3. Invoke the `gate-evaluator` subagent in a **fresh Task/Agent call** with the
   adversarial system prompt — the evaluator must not have context from the
   generation session
4. Write the JSON verdict to `.meridian/evaluator/<gate>-verdict.json`
5. Report the verdict and score; if FAIL, describe the top blocking issue

### `/evaluate --prepare <gate> [artifact ...]`

Prepare the evaluator request file without running the evaluation. Useful when
you want to queue an evaluation to run in a separate session.

```bash
# Under the hood:
bash "$PROJECT_DIR/.claude/hooks/run-evaluator.sh" --prepare <gate> [artifacts...]
```

### `/review`

Runs the Spec Reviewer subagent on CONTRACT.md + SPEC.md before the `confirmed`
gate is submitted. Writes output to `.meridian/evaluator/spec-review.json`.

---

## The separation rule

**Do not run `/evaluate` in the same session that built the artifacts.**

The enforced separation is the point — the same model that just wrote the code
will grade it charitably if asked in the same context. Open a new session, then:

```
/evaluate <gate>
```

The evaluator prompt explicitly states "You did not produce these artifacts."

---

## Verdict interpretation

| Verdict | Score | What happens |
|---------|-------|-------------|
| `pass` | ≥ 7.0 | `run-evaluator.sh --check` allows gate to proceed |
| `warn` | ≥ 5.0, no high issues | Allowed, warnings written to telemetry |
| `fail` | < 5.0 OR high issue | `run-evaluator.sh --check` **blocks** (exit 2) |
| Below threshold | `pass` verdict but score < `EVALUATOR_THRESHOLD` (default 7.0) | **Blocked** — score gates, not just verdict label |

---

## Files written

- `.meridian/evaluator/<gate>-verdict.json` — the verdict consumed by the hook
- Telemetry: `evaluator_verdict` event logged via `log-event.sh`

---

## When to use

- At every gate transition, before running `gate-engine.sh verify` and typing
  the approval token
- Before any significant architectural decision (use `/review` for spec gaps)
- When `/health` shows the evaluator_verdict trend is declining

---

**Status:** Complete (Gate 3.1) — backed by `.claude/agents/gate-evaluator.md`
