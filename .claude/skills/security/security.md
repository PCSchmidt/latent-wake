---
name: security
trigger: /security
purpose: Audit the security blocklist and what it has caught
type: wired
backing: scripts/security-audit.sh
load: on-invocation
tokens_metadata: 65
references: scripts/security-audit.sh, .claude/hooks/block-dangerous.sh, .meridian/security-rules.yaml
---

# Security Skill

**Skill:** security
**Trigger:** `/security`
**Purpose:** Audit Meridian's security posture — the active blocklist and what it has caught

---

## Commands

### `/security`

Full audit: active rules grouped by severity, plus a summary of security events
recorded in telemetry.

```bash
bash "$PROJECT_DIR/scripts/security-audit.sh" full
```

### `/security rules`

List the active rules from `.meridian/security-rules.yaml` (id, severity,
category).

```bash
bash "$PROJECT_DIR/scripts/security-audit.sh" rules
```

### `/security events`

Summarize security telemetry — counts of `blocked` / `warned` outcomes and the
rules that triggered them.

```bash
bash "$PROJECT_DIR/scripts/security-audit.sh" events
```

---

## How enforcement actually works

Live enforcement is **not** this skill — it is `block-dangerous.sh`, invoked by
`PreToolUse.sh` on every tool call. That hook scans Bash commands and Edit/Write
content against `security-rules.yaml` and **exits 2 (blocks)** on a deterministic
dangerous operation, or warns on a heuristic match. This skill is the
after-the-fact dashboard over that mechanism.

**Severity policy:**
- **block** — recursive root delete, `dd`/`mkfs`, fork bomb, AWS keys, private keys
- **warn** — SQLi heuristics, generic secret literals, `git reset --hard`

Edit `security-rules.yaml` to add project-specific rules or set a rule's
`severity` to `off` to disable it.

---

## Scope (honest)

This covers Meridian's own command/secret blocklist. It is not a full
application security audit (no dependency CVE scan, no SAST, no auth review).
Those belong to an end-user project's own gates and tooling.

---

**Status:** Complete (Gate 2.4) — wraps `scripts/security-audit.sh` over the
`block-dangerous.sh` enforcement built in Gate 2.1
