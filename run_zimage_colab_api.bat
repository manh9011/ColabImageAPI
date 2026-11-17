@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

REM =========================================================================
REM Auto-configures Python >= 3.12, creates .venv and launches Z-Image API.
REM Supports:
REM 1. uv (auto-downloads standalone Python 3.12 without system changes)
REM 2. Finds Python 3.12/3.13 via Windows Python Launcher (py -3.12 / py -3.13)
REM 3. Python Embeddable package if placed in python_embed\ folder
REM =========================================================================

echo "========================================================================="
echo "   INITIALIZING PYTHON >= 3.12 ENVIRONMENT FOR Z-IMAGE TURBO COLAB API"
echo "========================================================================="

REM -------------------------------------------------------------------------
REM Check if valid .venv already exists
REM -------------------------------------------------------------------------
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1
    if !ERRORLEVEL! equ 0 goto ACTIVATE_AND_INSTALL
)
set USE_UV=0
where uv >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set USE_UV=1
) else (
    REM Try uv via current python if installed
    python -m uv --version >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        set USE_UV=2
    )
)

if !USE_UV! gtr 0 (
    echo "[Preferred method] Tool 'uv' detected."
    echo "Creating virtual environment with auto-downloaded Python 3.12..."
    if !USE_UV! equ 1 (
        uv venv .venv --python 3.12
    ) else (
        python -m uv venv .venv --python 3.12
    )
    if !ERRORLEVEL! equ 0 (
        goto ACTIVATE_AND_INSTALL
    )
)

REM -------------------------------------------------------------------------
REM Check Python Launcher (py.exe) for Python 3.12 or 3.13
REM -------------------------------------------------------------------------
where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo "Checking Python Launcher (py -3.12 / py -3.13)..."
    py -3.12 -c "import sys; print(sys.version)" >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        echo "Found Python 3.12 via py launcher."
        py -3.12 -m venv .venv
        goto ACTIVATE_AND_INSTALL
    )
    py -3.13 -c "import sys; print(sys.version)" >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        echo "Found Python 3.13 via py launcher."
        py -3.13 -m venv .venv
        goto ACTIVATE_AND_INSTALL
    )
)

REM -------------------------------------------------------------------------
REM Check embeddable Python package in python_embed folder
REM -------------------------------------------------------------------------
if exist "python_embed\python.exe" (
    echo "Found Python Embeddable in python_embed\ folder."
    python_embed\python.exe -m pip install fastapi uvicorn pydantic requests google-colab-cli
    python_embed\python.exe zimage_colab_api.py %*
    exit /b 0
)

REM -------------------------------------------------------------------------
REM If current Python is < 3.12, auto-install uv via pip to fetch 3.12
REM -------------------------------------------------------------------------
echo.
echo "[!] WARNING: google-colab-cli requires Python >= 3.12."
echo.
echo "Auto-installing 'uv' via pip to fetch standalone Python 3.12:"
python -m pip install uv
if %ERRORLEVEL% equ 0 (
    echo "Installed uv successfully! Creating venv with Python 3.12..."
    python -m uv venv .venv --python 3.12
    goto ACTIVATE_AND_INSTALL
)

echo.
echo "[ERROR] Could not automatically set up Python 3.12."
echo "You can easily resolve this by doing one of the following:"
echo "1. Run: pip install uv"
echo "   Then re-run this script."
echo "2. Or install Python 3.12 / 3.13 from https://www.python.org/downloads/"
pause
exit /b 1

:ACTIVATE_AND_INSTALL
echo.
echo "=== [Activating Virtualenv and Installing Dependencies] ==="
call .venv\Scripts\activate.bat

python -c "import sys; print('Running on Python:', sys.version)"

REM Use uv pip if available to speed up installation
where uv >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo "Installing dependencies using uv pip..."
    if exist "requirements.txt" (
        uv pip install -r requirements.txt
    ) else (
        uv pip install fastapi uvicorn pydantic requests keyring
    )
    uv pip install "git+https://github.com/googlecolab/google-colab-cli.git" || uv pip install google-colab-cli
) else (
    echo "Installing dependencies using pip..."
    python -m pip install --upgrade pip
    if exist "requirements.txt" (
        python -m pip install -r requirements.txt
    ) else (
        python -m pip install fastapi uvicorn pydantic requests keyring
    )
    python -m pip install "git+https://github.com/googlecolab/google-colab-cli.git" || python -m pip install google-colab-cli
)

echo.
echo "========================================================================="
echo "   STARTING Z-IMAGE TURBO API SERVER (SINGLE-THREAD) - GOOGLE COLAB"
echo "========================================================================="
echo "Address: http://127.0.0.1:2504"
echo "Press Ctrl+C to stop."
echo "-------------------------------------------------------------------------"

python zimage_colab_api.py %*

pause
