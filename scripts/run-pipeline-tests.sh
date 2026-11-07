#!/bin/bash
# Latent Wake gate check (project-specific, not part of Meridian): unit tests for download, preprocessing, and injection.
# Exit 2 blocks the gate.
source "$(dirname "${BASH_SOURCE[0]}")/lw-env.sh"
lw_run "$LW_PY" -m pytest -q tests/test_download.py tests/test_preprocess.py tests/test_inject.py
