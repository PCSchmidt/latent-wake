---
name: review
trigger: /review
purpose: Run spec-reviewer on CONTRACT.md and SPEC.md before the confirmed gate clears
type: wired
backing: .claude/agents/spec-reviewer.md
load: on-invocation
tokens_metadata: 60
references: .claude/agents/spec-reviewer.md, .meridian/evaluator/spec-review.json
---

# Review Skill

**Trigger:** `/review`

## What it does

Runs the Spec Reviewer subagent on your project's specification documents before
the `confirmed` gate clears. Finds gaps, ambiguities, and contradictions that
would cause implementation failures — while they are still cheap to fix.

---

## Usage

### `/review`

Reviews CONTRACT.md, SPEC.md, and DECISIONS.md (if present) in the current
project directory. Writes structured findings to `.meridian/evaluator/spec-review.json`.

**What the reviewer checks:**
- CONTRACT.md: out-of-scope section, deployment target, measurable success criteria
- SPEC.md: all contract features present, acceptance criteria testable
- DECISIONS.md: rationale present, no contradictions with CONTRACT
- Cross-document: consistency across all three

### `/review --path <dir>`

Review spec documents in a different directory.

---

## Output

`.meridian/evaluator/spec-review.json`:
```json
{
  "verdict": "pass|warn|fail",
  "ready_to_proceed": true|false,
  "gaps": [...],
  "contradictions": [...],
  "overall_notes": "..."
}
```

A `fail` verdict means the spec has high-severity gaps that will cause
implementation failures — address them before submitting the `confirmed` gate.

---

## When to use

Run `/review` **before** typing the `confirmed` approval token. It is the
human-readable companion to `validate-contract.sh` (which checks structure)
and `validate-spec.sh` (which checks format) — those run mechanically; this
one runs the semantic gap-check.

---

**Status:** Complete (Gate 3.1) — backed by `.claude/agents/spec-reviewer.md`
