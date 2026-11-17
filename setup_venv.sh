#!/usr/bin/env bash
# =============================================================================
# Multi-Model Colab API Server - Virtual Environment (.venv) Setup Script
# Supported: Linux, macOS, and Git Bash (Windows)
# Requirements: Python >= 3.12 (mandated by google-colab-cli)
# =============================================================================

set -e

# Change to script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Color definitions
BOLD='\033[1m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=========================================================================${NC}"
echo -e "${BOLD}   SETTING UP PYTHON >= 3.12 ENVIRONMENT (.venv) FOR COLAB IMAGE API${NC}"
echo -e "${BLUE}=========================================================================${NC}"

# Function to check Python >= 3.12
check_py_ver() {
    local py_cmd="$1"
    if [ -f "$py_cmd" ] || command -v "$py_cmd" >/dev/null 2>&1; then
        if "$py_cmd" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

# 1. Check if .venv already exists and is valid (supports bin/ on Unix and Scripts/ on Windows)
VENV_PY=""
if [ -f ".venv/bin/python" ]; then
    VENV_PY=".venv/bin/python"
elif [ -f ".venv/Scripts/python.exe" ]; then
    VENV_PY=".venv/Scripts/python.exe"
fi

NEED_CREATE_VENV=1
if [ -n "$VENV_PY" ]; then
    if check_py_ver "$VENV_PY"; then
        echo -e "${GREEN}[OK] Valid .venv found with Python >= 3.12.${NC}"
        NEED_CREATE_VENV=0
    else
        echo -e "${YELLOW}[!] Current .venv uses Python < 3.12. Recreating .venv...${NC}"
        rm -rf .venv
        NEED_CREATE_VENV=1
    fi
elif [ -d ".venv" ]; then
    echo -e "${YELLOW}[!] Directory .venv is corrupted or incomplete. Recreating...${NC}"
    rm -rf .venv
    NEED_CREATE_VENV=1
fi

# Look for uv in common directories if not in PATH
if ! command -v uv >/dev/null 2>&1; then
    for uv_path in "$HOME/.cargo/bin/uv" "$HOME/.local/bin/uv"; do
        if [ -x "$uv_path" ]; then
            export PATH="$(dirname "$uv_path"):$PATH"
            break
        fi
    done
fi

HAS_UV=0
if command -v uv >/dev/null 2>&1; then
    HAS_UV=1
fi

if [ "$NEED_CREATE_VENV" -eq 1 ]; then
    echo -e "\n${BOLD}>>> Searching for Python >= 3.12 or tool 'uv'...${NC}"
    
    if [ "$HAS_UV" -eq 1 ]; then
        echo -e "${GREEN}[Preferred] Tool 'uv' detected. Creating .venv with Python 3.12 automatically...${NC}"
        uv venv .venv --python 3.12
    else
        # Search available python commands
        CHOSEN_PY=""
        for candidate in python3.13 python3.12 python3 python py; do
            if [ "$candidate" = "py" ]; then
                if py -3.12 -c 'import sys; sys.exit(0)' >/dev/null 2>&1; then
                    CHOSEN_PY="py -3.12"
                    break
                elif py -3.13 -c 'import sys; sys.exit(0)' >/dev/null 2>&1; then
                    CHOSEN_PY="py -3.13"
                    break
                fi
            elif check_py_ver "$candidate"; then
                CHOSEN_PY="$candidate"
                break
            fi
        done

        if [ -n "$CHOSEN_PY" ]; then
            echo -e "${GREEN}[OK] Found system Python: $($CHOSEN_PY --version)${NC}"
            echo "Creating virtual environment .venv using $CHOSEN_PY..."
            $CHOSEN_PY -m venv .venv
        else
            echo -e "${YELLOW}[!] Python >= 3.12 not found on the system.${NC}"
            echo -e "google-colab-cli requires Python >= 3.12."
            
            # Check if curl is available to install uv standalone
            if command -v curl >/dev/null 2>&1; then
                echo -e "\n${BOLD}Installing 'uv' to download standalone Python 3.12 without root (sudo)...${NC}"
                curl -LsSf https://astral.sh/uv/install.sh | sh
                for uv_path in "$HOME/.cargo/bin/uv" "$HOME/.local/bin/uv"; do
                    if [ -x "$uv_path" ]; then
                        export PATH="$(dirname "$uv_path"):$PATH"
                        HAS_UV=1
                        break
                    fi
                done
                if [ "$HAS_UV" -eq 1 ]; then
                    echo -e "${GREEN}[OK] Installed uv successfully! Creating .venv with Python 3.12...${NC}"
                    uv venv .venv --python 3.12
                fi
            fi

            if [ ! -d ".venv" ]; then
                echo -e "\n${RED}[ERROR] Could not automatically configure Python 3.12.${NC}"
                echo -e "Please install Python 3.12+ using one of the following methods:"
                echo -e "  - Fastest (no root required):       ${BOLD}curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
                echo -e "  - On Ubuntu/Debian:                 ${BOLD}sudo apt update && sudo apt install -y python3.12 python3.12-venv${NC}"
                echo -e "  - On macOS (Homebrew):              ${BOLD}brew install python@3.12${NC}"
                echo -e "  - On Arch Linux:                    ${BOLD}sudo pacman -S python${NC}"
                echo -e "  - On Fedora:                        ${BOLD}sudo dnf install python3.12${NC}"
                exit 1
            fi
        fi
    fi
fi

# 2. Activate virtual environment and install dependencies
echo -e "\n${BLUE}=== [Activating Virtualenv and Installing Dependencies] ===${NC}"
if [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
elif [ -f ".venv/Scripts/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/Scripts/activate
fi

# Determine python binary inside venv
if [ -f ".venv/bin/python" ]; then
    ACTIVE_PY=".venv/bin/python"
elif [ -f ".venv/Scripts/python.exe" ]; then
    ACTIVE_PY=".venv/Scripts/python.exe"
else
    ACTIVE_PY="python"
fi

echo "Running on Python: $("$ACTIVE_PY" -c 'import sys; print(sys.version.split()[0])')"

if [ "$HAS_UV" -eq 1 ]; then
    echo "Installing dependencies using uv pip (fast mode)..."
    if [ -f "requirements.txt" ]; then
        uv pip install -r requirements.txt
    else
        uv pip install fastapi uvicorn pydantic requests keyring
    fi
    uv pip install "git+https://github.com/googlecolab/google-colab-cli.git" || uv pip install google-colab-cli
else
    echo "Installing dependencies using standard pip..."
    "$ACTIVE_PY" -m pip install --upgrade pip
    if [ -f "requirements.txt" ]; then
        "$ACTIVE_PY" -m pip install -r requirements.txt
    else
        "$ACTIVE_PY" -m pip install fastapi uvicorn pydantic requests keyring
    fi
    "$ACTIVE_PY" -m pip install "git+https://github.com/googlecolab/google-colab-cli.git" || "$ACTIVE_PY" -m pip install google-colab-cli
fi

# 3. Verify integrity
echo -e "\n${BLUE}=== [Verifying Environment Integrity] ===${NC}"
"$ACTIVE_PY" -c "import fastapi, uvicorn, pydantic, requests, keyring; print('[OK] Core libraries: OK')"

VENV_COLAB=""
if [ -f ".venv/bin/colab" ]; then
    VENV_COLAB=".venv/bin/colab"
elif [ -f ".venv/Scripts/colab.exe" ]; then
    VENV_COLAB=".venv/Scripts/colab.exe"
fi

if [ -n "$VENV_COLAB" ] && "$VENV_COLAB" version >/dev/null 2>&1; then
    echo -e "${GREEN}[OK] google-colab-cli is ready to use!${NC}"
else
    echo -e "${YELLOW}[i] CLI colab has been installed into .venv.${NC}"
fi

# Grant execute permissions to shell scripts
chmod +x ./*.sh 2>/dev/null || true

echo -e "\n${BLUE}=========================================================================${NC}"
echo -e "${GREEN}${BOLD}   VIRTUAL ENVIRONMENT (.venv) SETUP COMPLETED!${NC}"
echo -e "   You can now launch the servers using:"
echo -e "   - ${BOLD}./run_zimage_colab_api.sh${NC}     (Port 2504)"
echo -e "   - ${BOLD}./run_qwen_colab_api.sh${NC}       (Port 2505)"
echo -e "   - ${BOLD}./run_minimax_h3_colab_api.sh${NC} (Port 2506)"
echo -e "${BLUE}=========================================================================${NC}"
