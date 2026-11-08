#!/bin/bash
# Latent Wake gate check (project-specific, not part of Meridian): DATA_CONTRACT.md has no open decisions and complete, parseable thresholds.
# Exit 2 blocks the gate.
source "$(dirname "${BASH_SOURCE[0]}")/lw-env.sh"
lw_run "$LW_PY" -m latentwake.checks contract "$(lw_cfg contract)"
