#!/bin/bash
# Latent Wake gate check (project-specific, not part of Meridian): evaluation results meet every criterion in DATA_CONTRACT.md.
# Exit 2 blocks the gate.
source "$(dirname "${BASH_SOURCE[0]}")/lw-env.sh"
lw_run "$LW_PY" -m latentwake.checks metrics "$(lw_cfg out)/results.csv" "$(lw_cfg contract)"
