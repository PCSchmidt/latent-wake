---
name: status
trigger: /status
purpose: Quick where-am-I report — gates completed, calibration, lifecycle completion
type: wired
backing: scripts/status-report.sh
load: on-invocation
tokens_metadata: 60
references: scripts/status-report.sh, scripts/features-report.sh, .meridian/FEATURES.json
---

# Status Skill

**Skill:** status  
**Trigger:** `/status`  
**Purpose:** Quick "where am I?" report for session start — gates completed, current gate, calibration

---

## Commands

### `/status`

Compact status report. Shows completed gates with dates and calibration ratios, current gate, and last activity timestamp. Designed to be read in under 10 seconds at the start of a session.

**Implementation:**
```bash
bash "$PROJECT_DIR/scripts/status-report.sh" full
```

**Example output:**
```
Project:  meridian
Gate:     1.6  (current)

Completed gates:

  ✓  G1.1    2026-05-28  0.75x
  ✓  G1.2    2026-05-28  1.0x
  ✓  G1.3    2026-05-29  1.0x
  ✓  G1.4    2026-06-01  1.0x
  ✓  G1.5    2026-06-01  1.0x

  Summary:             5 gates, avg 0.95x calibration

  Last activity:       2026-06-01T18:30:00Z

Feature lifecycle:

  90% happy-path / 50% full-lifecycle  (10 features)
```

The lifecycle line only appears when `.meridian/FEATURES.json` exists (seeded by `features-init.sh`).

---

### `/status --short`

One-line summary for minimal context use.

**Implementation:**
```bash
bash "$PROJECT_DIR/scripts/status-report.sh" --short
```

**Example output:**
```
meridian | gate 1.6 | 5 completed | cal 0.95x
```

---

### `/status --json`

Machine-readable JSON. Includes completed gates array for automation.

**Implementation:**
```bash
bash "$PROJECT_DIR/scripts/status-report.sh" --json
```

**Example output:**
```json
{
  "project": "meridian",
  "current_gate": "1.6",
  "gates_completed": 5,
  "avg_calibration": 0.95,
  "last_activity": "2026-06-01T18:30:00Z",
  "completed_gates": [
    {"gate": "1.1", "date": "2026-05-28T16:00:00Z", "ratio": 0.75},
    {"gate": "1.2", "date": "2026-05-28T17:30:00Z", "ratio": 1.0}
  ]
}
```

---

## When to Use

**Use `/status` when:**
- Starting a new session to re-orient quickly
- Checking progress before deciding what to work on next
- Confirming a gate completed correctly

**Use `/health report` when:**
- You want detailed calibration analysis
- Debugging telemetry or memory issues
- Doing a thorough project review

The key difference: `/status` answers "where am I?" in one screen. `/health` answers "how is the project performing?" in depth.

---

## Data Sources

| Field | Source |
|-------|--------|
| Current gate | `.meridian/session.json` |
| Completed gates | `.meridian/memory/corrections.jsonl` |
| Avg calibration | `.meridian/memory/corrections.jsonl` (computed) |
| Last activity | `.meridian/telemetry.jsonl` (last event) |
| Lifecycle completion | `.meridian/FEATURES.json` (seeded by `features-init.sh`) |

---

## Feature Lifecycle Commands

Initialize features from SPEC.md:
```bash
bash scripts/features-init.sh
```

Mark a lifecycle sub-state as complete (edit FEATURES.json directly or via script):
```bash
# Example: mark "auth" happy_path done
jq '(.[] | select(.id == "auth") | .lifecycle.happy_path) |= true' \
  .meridian/FEATURES.json > /tmp/f.json && mv /tmp/f.json .meridian/FEATURES.json
```

Full lifecycle breakdown:
```bash
bash scripts/features-report.sh
```

---

**Status:** Updated Gate 3.2 — lifecycle-aware completion added  
**Script:** `scripts/status-report.sh`, `scripts/features-init.sh`, `scripts/features-report.sh`  
**Related:** [`/health`](../health/health.md)
