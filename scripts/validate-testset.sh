#!/bin/bash
# Latent Wake gate check (project-specific, not part of Meridian): the frozen test set verifies its checksum and comes only from the test split.
# Exit 2 blocks the gate.
source "$(dirname "${BASH_SOURCE[0]}")/lw-env.sh"
lw_run "$LW_PY" -m latentwake.checks testset "$(lw_cfg testset)" "$(lw_cfg processed)"
