#!/bin/bash
# Latent Wake gate check (project-specific, not part of Meridian): cropped daily AIS files exist and no day failed to download or crop.
# Exit 2 blocks the gate.
source "$(dirname "${BASH_SOURCE[0]}")/lw-env.sh"
lw_run "$LW_PY" -m latentwake.checks schema "$(lw_cfg interim)"
