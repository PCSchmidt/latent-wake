---
name: rollback
trigger: /rollback
purpose: Revert the gate state to an earlier gate
type: wired
backing: scripts/rollback-gate.sh
load: on-invocation
tokens_metadata: 60
references: scripts/rollback-gate.sh, scripts/gate-engine.sh
---

# Rollback Skill

**Skill:** rollback
**Trigger:** `/rollback`
**Purpose:** Revert the gate state to an earlier gate when a closed gate turns out to be wrong

---

## Commands

### `/rollback --list`

Show the gates currently recorded as passed.

```bash
bash "$PROJECT_DIR/scripts/rollback-gate.sh" --list
```

### `/rollback`

Remove the most-recent passed gate from the gate state.

```bash
bash "$PROJECT_DIR/scripts/rollback-gate.sh"
```

### `/rollback --to <gate>`

Keep `<gate>` and remove every gate that comes after it (return to the state
where `<gate>` was the last completed gate).

```bash
bash "$PROJECT_DIR/scripts/rollback-gate.sh" --to 1.3
```

### `/rollback --dry-run`

Preview the change (combine with `--to`) without writing anything.

---

## What it does — and does not do

- **Does** rewrite `.meridian/gate-state.json` (after backing it up to
  `gate-state.json.bak`) so the gate DAG no longer considers the removed gates
  complete.
- **Does not** touch source code. Gate state and git history are deliberately
  separate. After rolling back, the skill prints git guidance to revert the
  matching commit (`git revert <commit>` to keep history, or `git reset --hard`
  to discard).

---

## When to use

Use when a completed gate was a mistake — a bad architectural decision, broken
work that cannot be cleanly fixed forward, or lost tests. For ordinary code
changes, use git directly; for aborting in-progress work before a gate closes,
just discard the branch.

---

**Status:** Complete (Gate 2.4) — wraps `scripts/rollback-gate.sh`
