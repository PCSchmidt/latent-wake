#!/bin/bash
# Latent Wake gate check (project-specific, not part of Meridian): every latent model with SIGReg on has 3+ seeds and none collapsed.
# Exit 2 blocks the gate.
source "$(dirname "${BASH_SOURCE[0]}")/lw-env.sh"
lw_run "$LW_PY" -m latentwake.checks training configs/eval.yaml
