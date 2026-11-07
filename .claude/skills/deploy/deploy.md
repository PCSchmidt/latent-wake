---
name: deploy
trigger: /deploy
purpose: Orchestrate the pre-deploy gate sequence before shipping
type: orchestration
backing: orchestration (no single script)
load: on-invocation
tokens_metadata: 60
references: .claude/hooks/run-tests.sh, scripts/security-audit.sh, .claude/hooks/run-evaluator.sh, scripts/gate-engine.sh
---

# Deploy Skill

**Skill:** deploy
**Trigger:** `/deploy`
**Purpose:** Orchestrate the pre-deploy gate sequence before shipping

---

## What this skill is

`/deploy` is an **orchestration** skill, not a deploy automation tool. Meridian
is stack-agnostic; the actual deploy command (Vercel, Fly, Docker, etc.) belongs
in your project's `gates.yaml` as a gate hook. This skill runs the universal
pre-deploy checks Meridian *can* enforce, in order, and stops at the first
failure.

---

## The pre-deploy sequence

Run for the deploy gate (e.g. `ready_to_ship`):

1. **Tests pass**
   ```bash
   bash "$PROJECT_DIR/.claude/hooks/run-tests.sh"
   ```
2. **Security clean**
   ```bash
   bash "$PROJECT_DIR/scripts/security-audit.sh" full
   ```
3. **Independent evaluation clears the bar**
   ```bash
   bash "$PROJECT_DIR/.claude/hooks/run-evaluator.sh" --check <deploy-gate>
   ```
4. **Gate dependencies + pre-hooks verified**
   ```bash
   bash "$PROJECT_DIR/scripts/gate-engine.sh" verify <deploy-gate>
   ```
5. **Operator approves the gate (only if 1–4 all pass)**. The deploy gate is
   a human approval gate: the agent reports readiness and the **operator** runs
   this in their own terminal (the PreToolUse hook blocks the agent from
   approving). mark-passed re-checks dependencies, artifacts, and pre-hooks.
   ```bash
   bash scripts/gate-engine.sh mark-passed <deploy-gate> --approve <approval_token>
   ```

Then run your project-specific deploy command (defined in `gates.yaml` hooks or
run manually).

---

## Scope (honest)

- **Wired:** the gate sequence above, using existing Meridian scripts.
- **Not built:** stack-specific deploy automation, health checks against a live
  URL, and CI/CD wiring. Those are end-user-project concerns; Meridian provides
  the gate scaffolding, not the deploy runner.

---

**Status:** Orchestration skill (Gate 2.4) — composes existing gate/test/security
scripts; deploy automation is out of framework scope
