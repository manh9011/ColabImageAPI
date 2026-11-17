@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

REM =========================================================================
REM Script to set up virtual environment .venv (Python >= 3.12) on Windows
REM Automatically supports:
REM 1. uv (auto-downloads standalone Python 3.12 WITHOUT system changes)
REM 2. Finds Python 3.12/3.13 via Windows Python Launcher (py -3.12 / py -3.13)
REM 3. Auto-installs uv if current system Python is < 3.12
REM =========================================================================

echo "========================================================================="
echo "   SETTING UP PYTHON >= 3.12 ENVIRONMENT (.venv) FOR COLAB IMAGE API"
echo "========================================================================="

REM -------------------------------------------------------------------------
REM Check if .venv already exists and has Python >= 3.12
REM -------------------------------------------------------------------------
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        echo "[OK] Valid .venv found with Python >= 3.12."
        goto ACTIVATE_AND_INSTALL
    ) else (
        echo "[!] Current .venv uses Python < 3.12. Recreating .venv..."
        rmdir /s /q .venv >nul 2>&1
    )
)

set USE_UV=0
where uv >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set USE_UV=1
) else (
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
REM Check if Windows Python Launcher (py.exe) has Python 3.12 or 3.13
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
REM Check default system python
REM -------------------------------------------------------------------------
where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        echo "Found system Python >= 3.12."
        python -m venv .venv
        goto ACTIVATE_AND_INSTALL
    )
)

REM -------------------------------------------------------------------------
REM If current Python is < 3.12, auto-install uv to fetch Python 3.12 standalone
REM -------------------------------------------------------------------------
echo.
echo "[!] WARNING: google-colab-cli requires Python >= 3.12."
echo "Auto-installing 'uv' via pip to download standalone Python 3.12:"
python -m pip install uv
if %ERRORLEVEL% equ 0 (
    echo "Successfully installed uv! Creating venv with Python 3.12..."
    python -m uv venv .venv --python 3.12
    if %ERRORLEVEL% equ 0 goto ACTIVATE_AND_INSTALL
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

REM Use uv pip if uv is available to speed up installation by 10x-100x
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
echo "=== [Verifying Environment Integrity] ==="
python -c "import fastapi, uvicorn, pydantic, requests, keyring; print('[OK] Core libraries: OK')"
.venv\Scripts\colab.exe version >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo "[OK] google-colab-cli is ready to use!"
) else (
    echo "[i] CLI colab has been installed into .venv."
)

echo.
echo "========================================================================="
echo "   VIRTUAL ENVIRONMENT (.venv) SETUP COMPLETED SUCCESSFULLY!"
echo "   You can now launch the servers using:"
echo "   - run_zimage_colab_api.bat     (Port 2504)"
echo "   - run_qwen_colab_api.bat       (Port 2505)"
echo "   - run_minimax_h3_colab_api.bat (Port 2506)"
echo "========================================================================="
pause
