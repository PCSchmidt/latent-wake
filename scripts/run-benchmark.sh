#!/bin/bash
# Latent Wake gate check (project-specific, not part of Meridian): models trained after the test set froze; score every model on it.
# Exit 2 blocks the gate.
source "$(dirname "${BASH_SOURCE[0]}")/lw-env.sh"
lw_run "$LW_PY" -m latentwake.checks benchmark configs/eval.yaml
