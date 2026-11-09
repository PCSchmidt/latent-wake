# CLAUDE.md

Session-start guidance for this project with Meridian. Keep under 60 lines.

## This project

Latent Wake: a trajectory JEPA that flags anomalous AIS vessel tracks. Plan in
`docs/SCOPE.md`; success criteria in `DATA_CONTRACT.md`; decision log in
`DECISIONS.md`; gate check paths in `configs/eval.yaml`. Rules that matter:
- Never train on real data before `data_contract` passes, and never before the
  test set is frozen (`validate-testset.sh`, `run-benchmark.sh` enforce this).
- Never tune against a test set; calibrate on validation only. Contract v2: Class A
  only; behavioral kinds only in moving transit vessels, scored against those.
- Owner-approval gates are approved by Chris in his own terminal, not by an agent.

## What Meridian is

An agent harness: enforces gates, tracks feature lifecycle, detects scope
drift, emits telemetry. Hooks fire automatically on tool use.

## Where things live

- `.claude/hooks/` — PreToolUse / PostToolUse enforcement (source `hook-wrapper.sh`, never execute it)
- `.claude/skills/` — slash-command skills: `/start`, `/health`, `/status`, `/memory`,
  `/security`, `/testing`, `/costs`, `/rollback`, `/deploy`, `/build-rules`,
  `/critical-thinker`, `/research`, `/drift-check`, `/evaluate`, `/review`
- `.claude/agents/` — subagent docs: `gate-evaluator`, `drift-evaluator`, `spec-reviewer`
- `.meridian/` — runtime state (gitignored: `memory/`, `telemetry.jsonl`, `session.json`)
  and tracked config: `gates.yaml`, `security-rules.yaml`, schemas, `FEATURES.json`

## Gate model

Work proceeds gate-by-gate (defined in `.meridian/gates.yaml`). Each gate:
build → test → update docs → write reflexion → commit. One gate at a time.

Key scripts (sourced from Meridian install — run from project root):
```
bash .meridian/../scripts/features-report.sh --full   # lifecycle completion
bash .meridian/../scripts/drift-check.sh --prepare    # prepare drift evaluation
bash .meridian/../scripts/drift-check.sh --check      # read drift verdict
```

## Feature lifecycle

Features are tracked in `.meridian/FEATURES.json`. Each feature has five states:
`happy_path`, `integration`, `edge_cases`, `error_handling`, `hardening`.

A feature is **not done** until all five states are true. "It works" = `happy_path` only.

## Enforcement

- `PreToolUse` blocks deterministic dangerous operations (see `security-rules.yaml`)
- Gate evaluator requires a passing verdict file before a gate can be marked complete
- Drift sensor is advisory — `drifted` recommendation is a warning, not a block

## Before committing

- Run relevant tests — all must pass
- Update `.meridian/FEATURES.json` lifecycle states to reflect actual completion
- Commit messages should describe the *why*, not the *what*
