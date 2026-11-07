---
name: costs
trigger: /costs
purpose: Report token usage and estimated spend from telemetry
type: wired
backing: scripts/cost-report.sh
load: on-invocation
tokens_metadata: 60
references: scripts/cost-report.sh, .meridian/telemetry-schema.json, MERIDIAN_ARCHITECTURE_DECISIONS.md
---

# Costs Skill

**Skill:** costs
**Trigger:** `/costs`
**Purpose:** Report token usage and estimated spend from telemetry

---

## Commands

### `/costs`

Summarize cost data aggregated from `telemetry.jsonl`: total events, how many
carry cost data, input/output tokens, and estimated USD.

```bash
bash "$PROJECT_DIR/scripts/cost-report.sh"
```

### `/costs --json`

Machine-readable aggregate (adds `captured` boolean and a status note).

```bash
bash "$PROJECT_DIR/scripts/cost-report.sh" --json
```

---

## Honest status

Cost tracking was reclassified from "Must Have" to Phase 2 (see
`MERIDIAN_ARCHITECTURE_DECISIONS.md` Decision 4) because the Phase 1 hook layer
does not expose a token-usage data source. The telemetry schema reserves three
optional stub fields — `input_tokens`, `output_tokens`, `cost_usd` — and
`cost-report.sh` aggregates them now.

Until a token source populates those fields, `/costs` will honestly report zero
captured. The aggregation is already wired, so the report lights up the moment
events start carrying cost data — no format change required.

This is deliberate: Meridian does not fabricate cost numbers it cannot measure.

---

**Status:** Aggregation complete (Gate 2.4); capture pending a token-usage source
(reserved stub fields, Decision 4)
