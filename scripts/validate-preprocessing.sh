#!/bin/bash
# Latent Wake gate check (project-specific, not part of Meridian): processed outputs exist, enough windows, all values finite.
# Exit 2 blocks the gate.
source "$(dirname "${BASH_SOURCE[0]}")/lw-env.sh"
lw_run "$LW_PY" -m latentwake.checks preprocessing "$(lw_cfg processed)"
