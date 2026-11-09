#!/bin/bash
# Latent Wake gate check (project-specific, not part of Meridian): evaluation results meet every criterion in DATA_CONTRACT.md.
# Exit 2 blocks the gate.
source "$(dirname "${BASH_SOURCE[0]}")/lw-env.sh"
# --record: the model_eval gate certifies that the test set was scored once and
# reported; a missed criterion is recorded in criteria.json, not blocked
# (owner decision 2026-11-09, made before the test set was scored).
lw_run "$LW_PY" -m latentwake.checks metrics "$(lw_cfg out)/results.csv" "$(lw_cfg contract)" --record
