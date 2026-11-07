---
name: drift-check
trigger: /drift-check
purpose: Detect goal drift between CONTRACT/SPEC commitments and current implementation — advisory only
type: wired
backing: scripts/drift-check.sh, .claude/agents/drift-evaluator.md
load: on-invocation
tokens_metadata: 65
references: scripts/drift-check.sh, .claude/agents/drift-evaluator.md, .meridian/drift/
---

# Drift Check Skill

**Skill:** drift-check  
**Trigger:** `/drift-check`  
**Purpose:** Run the drift-evaluator subagent against current project state. Returns alignment score, divergence list, and recommendation. Advisory only — warns, never blocks.

---

## Commands

### `/drift-check`

Full drift evaluation. Prepares context from CONTRACT.md, SPEC.md, git history, and FEATURES.json, then invokes the drift-evaluator subagent.

**Implementation:**
```bash
# Step 1: prepare context
bash "$PROJECT_DIR/scripts/drift-check.sh" --prepare

# Step 2: invoke drift-evaluator subagent (reads drift-request.json,
#         writes drift-verdict.json)
# [Agent: drift-evaluator reads .meridian/drift/drift-request.json]

# Step 3: report results
bash "$PROJECT_DIR/scripts/drift-check.sh" --check
```

**Example output:**
```
Drift Report  (2026-06-02T18:00:00Z)
──────────────────────────────────────
  Alignment score:  8/10
  Recommendation:   aligned

  No drift detected.
```

**Drifted example:**
```
Drift Report  (2026-06-02T18:00:00Z)
──────────────────────────────────────
  Alignment score:  4/10
  Recommendation:   drifted

  Divergences (2):

  [HIGH] scope_creep: AUTH_MODULE work is outside contracted CLI-tool scope
  [MEDIUM] feature_lag: EXPORT feature committed in CONTRACT but has 0 lifecycle states true

  Implementation has diverged from CONTRACT scope. AUTH_MODULE must be removed or
  CONTRACT updated via a recorded decision.

  Advisory only — review divergences above. No gates blocked.
```

---

### `/drift-check --check`

Re-read the last verdict without re-running the evaluator. Useful for surfacing the drift report in a new session.

**Implementation:**
```bash
bash "$PROJECT_DIR/scripts/drift-check.sh" --check
```

---

## When to Use

**Use `/drift-check` when:**
- Starting a new gate and want to verify you're still aligned with CONTRACT
- A session has run longer than expected and scope may have shifted
- After a significant implementation phase before marking a gate complete

**Use `/status` when:**
- You want gate progress and lifecycle completion (no drift analysis)

**Do NOT use as a gate blocker** — this sensor is advisory by design until
G3.4 validates it discriminates cleanly. See ROADMAP G3.3 and G3.4.

---

## Data Sources

| Field | Source |
|-------|--------|
| Contract scope | `CONTRACT.md` (first 40 lines) |
| Feature spec | `SPEC.md` (first 40 lines) |
| Git history | `git log --oneline -10` + diff stat |
| Lifecycle state | `.meridian/FEATURES.json` |
| Verdict | `.meridian/drift/drift-verdict.json` (written by evaluator) |

---

## Telemetry

Every `--check` call appends a `drift_score` event to `.meridian/telemetry.jsonl`:

```json
{
  "event_type": "drift_score",
  "alignment_score": 8,
  "recommendation": "aligned",
  "divergences": 0
}
```

`/health` will show the drift_score trend once G3.3 is wired to health-report.sh.

---

**Status:** Gate 3.3 — advisory drift sensor  
**Script:** `scripts/drift-check.sh`  
**Agent:** `.claude/agents/drift-evaluator.md`  
**Related:** [`/evaluate`](../evaluate/evaluate.md), [`/status`](../status/status.md)
