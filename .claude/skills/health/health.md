---
name: health
trigger: /health
purpose: Generate an engineer-legible health report for the project
type: wired
backing: scripts/health-report.sh
load: on-invocation
tokens_metadata: 60
references: scripts/health-report.sh, scripts/telemetry-query.sh
---

# Health Skill

**Skill:** health  
**Trigger:** `/health`  
**Purpose:** Generate an engineer-legible health report for the current Meridian project

---

## Commands

### `/health report`

Generates a full health report covering four sections:
- **Session** — Active session ID, current gate, tool usage count, error count
- **Gate Calibration** — Predicted vs actual hours per gate, operator multiplier trend and assessment
- **Memory Health** — Semantic pattern count by confidence tier, episodic event count, corrections count
- **Telemetry** — Event breakdown by type, error rate, top tools used

**Implementation:**
```bash
bash "$PROJECT_DIR/scripts/health-report.sh" full
```

---

### `/health gates`

Shows only the gate calibration section. Useful when you want a quick read on estimate accuracy without the full report.

**Implementation:**
```bash
bash "$PROJECT_DIR/scripts/health-report.sh" gates
```

**Example output:**
```
━━━ Gate Calibration ━━━

  Gate   Predicted  Actual  Ratio   Variance
  ──────────────────────────────────────────
  G1.1   8h         6h      0.75x  -25%
  G1.2   10h        10h     1.0x   0%
  G1.3   8h         8h      1.0x   0%
  G1.4   6h         6h      1.0x   0%

  Gates tracked:         4
  Avg operator mult:     0.94x
  Range:                 0.75x – 1.0x

  Calibration: GOOD (avg within 15% of target)
```

---

### `/health memory`

Shows only the memory health section.

**Implementation:**
```bash
bash "$PROJECT_DIR/scripts/health-report.sh" memory
```

---

### `/health telemetry`

Shows only the telemetry section.

**Implementation:**
```bash
bash "$PROJECT_DIR/scripts/health-report.sh" telemetry
```

---

### `/health --json`

Outputs machine-readable JSON. Use for automation, CI checks, or feeding into other tools.

**Implementation:**
```bash
bash "$PROJECT_DIR/scripts/health-report.sh" --json
```

**Output shape:**
```json
{
  "project": "my-project",
  "timestamp": "2026-05-28T14:00:00Z",
  "session_id": "6a1dc5ea",
  "current_gate": "1.5",
  "calibration": {
    "gates_tracked": 4,
    "avg_operator_multiplier": 0.94
  },
  "memory": {
    "semantic_patterns": 2
  },
  "telemetry": {
    "total_events": 24
  }
}
```

---

## How to Interpret

### Gate Calibration

The **operator multiplier** (stored as `delta_ratio` in `corrections.jsonl`) measures how accurately gates were estimated:

| Range | Meaning | Color |
|-------|---------|-------|
| 0.95x – 1.05x | Excellent — within 5% of target | Green |
| 0.85x – 1.15x | Good — within 15% of target | Green |
| 0.70x – 0.85x | Fast — finishing ahead of estimate | Yellow |
| < 0.70x | Very fast — estimates are too conservative | Red |
| > 1.15x | Slow — running over estimate | Red |

**Target:** converge toward 1.0x over time as your estimation improves.

### Memory Health

- **LOW confidence patterns** have been observed fewer than 3 times — they need more validation before being relied upon. Watch for them; they may not generalize.
- **>200 episodic events** — run `/memory prune` or `bash scripts/memory-doctor.sh` to keep file manageable.

### Error Rate

Errors in telemetry indicate hook or script failures. Zero is the target.  
To investigate: `bash scripts/telemetry-query.sh errors`

---

## Data Sources

| Section | Source file |
|---------|-------------|
| Session | `.meridian/session.json` |
| Gate Calibration | `.meridian/memory/corrections.jsonl` |
| Memory Health | `.meridian/memory/semantic.json`, `episodic.jsonl`, `corrections.jsonl` |
| Telemetry | `.meridian/telemetry.jsonl` |

---

## Related Commands

- `/memory doctor` — deep memory validation and deduplication
- `bash scripts/telemetry-query.sh summary` — raw telemetry query
- `bash scripts/session.sh status` — current session state

---

**Status:** Implemented in Gate 1.5  
**Script:** `scripts/health-report.sh`
