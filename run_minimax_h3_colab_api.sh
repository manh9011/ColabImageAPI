#!/usr/bin/env bash
# =============================================================================
# Launch MiniMax H3-Image Colab API Server (Port 2506) on Linux / macOS
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export PYTHONIOENCODING=utf-8

VENV_PY=""
if [ -f ".venv/bin/python" ]; then
    VENV_PY=".venv/bin/python"
elif [ -f ".venv/Scripts/python.exe" ]; then
    VENV_PY=".venv/Scripts/python.exe"
fi

# Automatically run setup_venv.sh if .venv does not exist
if [ -z "$VENV_PY" ]; then
    echo "========================================================================="
    echo "   NO .VENV DETECTED, RUNNING SETUP_VENV.SH AUTOMATICALLY..."
    echo "========================================================================="
    bash ./setup_venv.sh
    if [ -f ".venv/bin/python" ]; then
        VENV_PY=".venv/bin/python"
    elif [ -f ".venv/Scripts/python.exe" ]; then
        VENV_PY=".venv/Scripts/python.exe"
    fi
fi

if [ -z "$VENV_PY" ]; then
    echo "[ERROR] Python executable not found in .venv after initialization."
    exit 1
fi

echo "========================================================================="
echo "   STARTING MINIMAX H3 API SERVER (SINGLE-THREAD) - GOOGLE COLAB"
echo "========================================================================="
echo "Address: http://127.0.0.1:2506"
echo "Press Ctrl+C to stop."
echo "-------------------------------------------------------------------------"

exec "$VENV_PY" minimax_h3_colab_api.py "$@"
