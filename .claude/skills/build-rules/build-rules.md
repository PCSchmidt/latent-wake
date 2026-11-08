---
name: build-rules
trigger: /build-rules
purpose: Define a project gate DAG before any code is written
type: process
backing: process (no script)
load: on-invocation
tokens_metadata: 55
references: scripts/gate-engine.sh, .meridian/gate-schema.yaml, recipes/
---

# Build Rules Skill

**Skill:** build-rules
**Trigger:** `/build-rules`
**Purpose:** Define a project's gate DAG before any code is written

---

## What this skill is

A **process** skill (no backing script). It guides authoring a project's
`.meridian/gates.yaml` — the composable gate graph that everything else
enforces. Adapted from Syntaris' five-phase interrogation, but Meridian's output
is a gate DAG, not a fixed ladder.

---

## The flow

1. **Purpose & scope** — what is being built, what is explicitly out of scope.
   Capture in `CONTRACT.md` (validated later by `validate-contract.sh`).
2. **Pick a recipe** — start from `recipes/{fullstack-web,cli-tool,ml-research}/gates.yaml`
   as a reference; recipes are patterns, not prescriptions. Adapt to the stack.
3. **Define gates** — for each checkpoint set: `id`, `type`
   (`human_approval` | `automated`), `requires` (dependencies),
   `requires_artifacts`, `hooks.pre` / `hooks.post`, and `on_fail`.
4. **Validate the DAG**
   ```bash
   bash "$PROJECT_DIR/scripts/gate-engine.sh" validate
   bash "$PROJECT_DIR/scripts/gate-engine.sh" check-circular
   ```
5. **Confirm scope** — human approval before building. The first gate is
   typically `confirmed` with an approval token.

---

## Discipline

- One feature / one gate at a time (Assumption A001).
- Gates are mandatory (no skipping) but not hardcoded — they live in your
  `gates.yaml`.
- Wire enforcement into `hooks.pre` (e.g. `validate-spec.sh`, `run-tests.sh`,
  `run-evaluator.sh`) so the gate cannot be hallucinated past.

---

## Reference

- `.meridian/gate-schema.yaml` — full field documentation for a valid gate
- `recipes/*/gates.yaml` — worked examples per project pattern

---

**Status:** Process skill (Gate 2.4) — guidance over `gate-engine.sh` and the
recipe gate definitions
