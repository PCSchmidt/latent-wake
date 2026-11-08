---
name: start
trigger: /start
purpose: Begin or resume a work session and show where you are
type: wired
backing: scripts/start-session.sh
load: on-invocation
tokens_metadata: 60
references: scripts/start-session.sh, scripts/status-report.sh, scripts/session.sh
---

# Start Skill

**Skill:** start
**Trigger:** `/start`
**Purpose:** Begin or resume a Meridian work session and surface "where am I?"

---

## Commands

### `/start`

Bootstraps a session: resumes the existing one (or starts a fresh session),
prints the compact status report, names the current gate, and runs a fast
memory sanity check.

**Implementation:**
```bash
bash "$PROJECT_DIR/scripts/start-session.sh"
```

### `/start --new`

Forces a fresh session even if one exists (new `session_id`, resets counters).

### `/start --project <name>`

Starts a session with an explicit project name (defaults to the directory name).

---

## What it shows

1. **Session** — resumed id, or a newly minted 8-char hex session id
2. **Status** — completed gates with calibration, current gate, last activity
   (via `status-report.sh`)
3. **Current gate** — from `gate-engine.sh current` when a `gates.yaml` exists;
   otherwise notes that gate enforcement is inactive
4. **Memory check** — quick `memory-doctor.sh` pass/fail

---

## Notes

- Reading `/start` output is meant to take well under a minute — it is the
  session-open ritual, not a deep audit. Use `/health` for depth.
- If there is no `gates.yaml`, Meridian runs in permissive mode (no gate DAG).
  The session, telemetry, and memory layers still operate.

---

**Status:** Complete (Gate 2.4) — wraps `scripts/start-session.sh`
