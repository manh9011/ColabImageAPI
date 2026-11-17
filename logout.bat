@echo off
cd /d "%~dp0"
echo =========================================================================
echo    GOOGLE ACCOUNT LOGOUT IN GOOGLE-COLAB-CLI
echo =========================================================================
.venv\Scripts\python.exe -c "import keyring; keyring.delete_password('google-colab-cli', 'oauth_token')" 2>nul
echo.
echo [OK] Successfully removed old account token!
echo Now simply re-run your desired run_...colab_api.bat script; the browser will automatically open
echo allowing you to sign in with another Google account (one with available free GPU quota).
echo.
pause
