---
name: memory
trigger: /memory
purpose: Manage and validate the three-tier memory system
type: wired
backing: scripts/validate-memory.sh
load: on-invocation
tokens_metadata: 75
references: scripts/validate-memory.sh, scripts/memory-doctor.sh, scripts/write-reflexion.sh, scripts/global-memory-sync.sh, scripts/context-trim.sh
---

# Memory Management Skill

**Skill:** memory  
**Trigger:** `/memory`  
**Purpose:** Manage and validate Meridian's three-tier memory system

---

## Commands

### `/memory doctor`

Validates all memory files, checks for corruption, deduplicates patterns, and reports health.

**What it does:**
1. Validates semantic.json against schema
2. Validates episodic.jsonl (line-by-line)
3. Validates corrections.jsonl (line-by-line)
4. Deduplicates semantic patterns by hash
5. Checks for corruption or malformed entries
6. Reports memory health statistics

**Example output:**
```
Memory Health Check

✓ Semantic memory: 42 patterns, 3 duplicates removed, schema valid
✓ Episodic memory: 127 events, all valid
✓ Corrections memory: 16 gates, schema valid, avg calibration 0.73x
! Warning: semantic pattern PAT-001 has confidence:LOW (only 1 validation)

Memory health: GOOD
```

---

### `/memory show <type>`

Displays human-readable view of memory (converts JSONL to markdown).

**Arguments:**
- `semantic` - Show validated patterns
- `episodic` - Show recent session events
- `corrections` - Show reflexion entries with calibration data

**Example:**
```
/memory show corrections

Recent Corrections (newest first):

Gate v0.3: predicted 4h, actual 6h (0.67x)
  Root cause: Underestimated frontend complexity
  Action: Apply 1.5x to similar tasks
  
Gate v0.2: predicted 3h, actual 3.2h (0.94x)
  Root cause: Accurate estimate, minor scope creep
  Action: Maintain current estimation approach
```

---

### `/memory stats`

Shows memory statistics and trends.

**What it reports:**
- Total patterns (semantic)
- Confidence distribution (LOW/MEDIUM/HIGH)
- Total events (episodic)
- Total corrections
- Operator multiplier trend
- Estimate accuracy over time

---

### `/memory prune`

Trims episodic memory to the last N sessions to prevent unbounded growth. Older
events are archived (not deleted) to `episodic-archive.jsonl`.

```bash
bash "$PROJECT_DIR/scripts/context-trim.sh" -n 10        # keep last 10 sessions
bash "$PROJECT_DIR/scripts/context-trim.sh" -n 10 --dry-run
```

**Default:** Keep last 10 sessions (`EPISODIC_KEEP_SESSIONS`)

---

### `/memory reflect`

Append a calibration/reflexion entry to `corrections.jsonl` at gate close —
computes `delta_ratio` and `variance_percent`, write-ahead validates against the
schema, and logs a `memory_write` telemetry event.

```bash
bash "$PROJECT_DIR/scripts/write-reflexion.sh" \
  --gate <id> --predicted <h> --actual <h> \
  --root-cause "<why>" --action-next "<next>"
```

---

### `/memory sync`

Sync local memory with the global cross-project store at `~/.meridian/global/`.

```bash
bash "$PROJECT_DIR/scripts/global-memory-sync.sh" status   # local vs global counts
bash "$PROJECT_DIR/scripts/global-memory-sync.sh" push     # merge local -> global
bash "$PROJECT_DIR/scripts/global-memory-sync.sh" pull     # merge global -> local
```

Semantic patterns merge by `hash`; corrections merge by
`(session_id, gate, date, project)` identity, so repeated pushes are idempotent.

---

## Implementation

When user invokes `/memory doctor`:

1. Run validation scripts:
   ```bash
   ./scripts/validate-memory.sh semantic .meridian/memory/semantic.json
   ./scripts/validate-memory.sh episodic .meridian/memory/episodic.jsonl
   ./scripts/validate-memory.sh corrections .meridian/memory/corrections.jsonl
   ```

2. Check for warnings:
   - Patterns with confidence:LOW (validated_count < 3)
   - Episodic file > 200 events (suggest prune)
   - Missing fields or malformed entries

3. Report summary with clear status

---

## Memory File Locations

- **Project-local:**
  - `.meridian/memory/semantic.json` - Project-specific patterns
  - `.meridian/memory/episodic.jsonl` - Session events
  - `.meridian/memory/corrections.jsonl` - Reflexion entries

- **Global** (managed by `global-memory-sync.sh`):
  - `~/.meridian/global/semantic.json` - Cross-project patterns (merged by hash)
  - `~/.meridian/global/corrections.jsonl` - Cross-project calibration entries

---

## Usage Notes

- Memory files are JSONL internally (engineer-queryable)
- `/memory show` renders human-readable views (no need to read raw JSONL)
- Schema validation runs automatically on writes via PostToolUse hook
- `/memory doctor` is for manual health checks and recovery

---

## Error Recovery

If corruption detected:

1. `/memory doctor` will report the specific issue
2. Backup corrupt file: `cp file.json file.json.corrupt`
3. Fix manually or regenerate from git history
4. Re-run `/memory doctor` to verify

---

**Status:** Complete — validation + doctor (Gate 1.2); reflexion writer, global
sync, and episodic trim (Gate 2.3); skill commands wired (Gate 2.4)
