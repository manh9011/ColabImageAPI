#!/usr/bin/env bash
# =============================================================================
# Logout Google Colab account in google-colab-cli (remove OAuth token)
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================================================="
echo "   GOOGLE ACCOUNT LOGOUT IN GOOGLE-COLAB-CLI"
echo "========================================================================="

PYTHON_BIN=""
if [ -f ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

if [ -n "$PYTHON_BIN" ]; then
    "$PYTHON_BIN" -c "import keyring; keyring.delete_password('google-colab-cli', 'oauth_token')" 2>/dev/null || true
    echo ""
    echo "[OK] Successfully removed old account token!"
    echo "Now simply re-run your desired run_...colab_api.sh script; the browser will automatically open"
    echo "allowing you to sign in with another Google account (one with available free GPU quota)."
    echo ""
else
    echo "[!] Python executable not found to remove token."
    exit 1
fi
