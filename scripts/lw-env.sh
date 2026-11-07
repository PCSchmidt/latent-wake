#!/bin/bash
# Latent Wake helper sourced by the project's gate checks (not part of Meridian).
# Finds the project root and a Python interpreter, and reads paths from
# configs/eval.yaml. Any failure in a check maps to exit 2, which blocks the gate.

LW_ROOT="${MERIDIAN_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$LW_ROOT" || exit 2

if [ -n "${PYTHON:-}" ]; then LW_PY="$PYTHON"
elif [ -x .venv/bin/python ]; then LW_PY=.venv/bin/python
elif [ -x .venv/Scripts/python.exe ]; then LW_PY=.venv/Scripts/python.exe
elif command -v python3 >/dev/null 2>&1; then LW_PY=python3
else LW_PY=python
fi

lw_cfg() {
    "$LW_PY" -c "import sys, yaml; print(yaml.safe_load(open('configs/eval.yaml'))[sys.argv[1]])" "$1"
}

lw_run() {
    "$@"
    local rc=$?
    [ "$rc" -eq 0 ] && return 0
    echo "  (check exited $rc; blocking)" >&2
    exit 2
}
