---
name: research
trigger: /research
purpose: Run memory-first competitive and framework research
type: process
backing: process (no script)
load: on-invocation
tokens_metadata: 55
references: scripts/memory-doctor.sh, scripts/global-memory-sync.sh
---

# Research Skill

**Skill:** research
**Trigger:** `/research`
**Purpose:** Run competitive / framework research — memory-first, to avoid redundant work

---

## What this skill is

A **process** skill (no backing script). It structures research for a new
project or a tech-stack decision, and — critically — checks memory before
spending effort, so the same investigation is not repeated across sessions or
projects.

---

## The flow

1. **Check memory first**
   ```bash
   bash "$PROJECT_DIR/scripts/memory-doctor.sh"          # health
   ```
   Review semantic patterns and prior corrections for relevant findings:
   `/memory show semantic` and `/memory show corrections`. Also check the global
   store (`global-memory-sync.sh status`) for cross-project patterns.
2. **Scope the question** — what decision does this research serve? (Tie it to a
   pending gate or a `/critical-thinker` review.)
3. **Gather** — framework docs, comparable implementations, known failure modes.
4. **Synthesize** — a short comparison with a recommendation, not a link dump.
5. **Persist the finding** — capture a durable, reusable conclusion as a semantic
   pattern so future sessions benefit. Validated patterns sync globally via
   `global-memory-sync.sh push`.

---

## Discipline

- Memory-first is the point: redundant research is the cost this skill exists to
  cut. If memory already answers it, stop.
- Record conclusions, not raw searches — the next session needs the *finding*.
- Single-operator findings are not benchmarks; record confidence honestly
  (LOW / MEDIUM / HIGH per the memory schema).

---

**Status:** Process skill (Gate 2.4) — research workflow over the memory system
(`memory-doctor.sh`, `global-memory-sync.sh`)
