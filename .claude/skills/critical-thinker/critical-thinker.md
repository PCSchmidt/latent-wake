---
name: critical-thinker
trigger: /critical-thinker
purpose: Pressure-test a significant decision before it locks
type: process
backing: process (no script)
load: on-invocation
tokens_metadata: 55
references: ASSUMPTIONS.md, MERIDIAN_ARCHITECTURE_DECISIONS.md
---

# Critical Thinker Skill

**Skill:** critical-thinker
**Trigger:** `/critical-thinker`
**Purpose:** Pressure-test a significant decision before it gets locked into a gate

---

## What this skill is

A **process** skill (no backing script). It runs an adversarial review of a
proposed decision — tech stack, agent architecture, schema change, or anything
affecting 3+ future gates — before that decision is committed.

It is the human-decision analogue of the generator-evaluator separation (A003):
the reviewer's job is to find what is wrong, not to validate.

---

## The pressure test

For the proposed decision, force answers to:

1. **Failure modes** — how does this break? What is the worst realistic outcome?
2. **Reversibility** — if wrong, how expensive is the unwind? (One-way vs
   two-way door.)
3. **Alternatives** — what are 2–3 other options, and why are they rejected?
   ("None considered" is a red flag.)
4. **Assumptions** — what must be true for this to work? Are those in
   `ASSUMPTIONS.md`? Will they survive a model upgrade?
5. **Cost & lock-in** — what does it cost now and ongoing, and what does it
   foreclose later? (Cross-check with `/costs`.)
6. **Evidence** — is this grounded, or vibes? What would change the decision?

A decision that cannot survive these questions is not ready to lock.

---

## Output

A short written verdict: **proceed / proceed-with-changes / reconsider**, the
top unresolved risk, and any new assumption to record in `ASSUMPTIONS.md`.
Significant decisions and their rationale belong in `DECISIONS.md` (or
`MERIDIAN_ARCHITECTURE_DECISIONS.md` for Meridian itself).

---

**Status:** Process skill (Gate 2.4) — decision governance; pairs with
`ASSUMPTIONS.md` and the architecture-decisions log
