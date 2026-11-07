#!/bin/bash
# Latent Wake gate check (project-specific, not part of Meridian): the full test suite, including model, training, and evaluation.
# Exit 2 blocks the gate.
source "$(dirname "${BASH_SOURCE[0]}")/lw-env.sh"
lw_run "$LW_PY" -m pytest -q tests
