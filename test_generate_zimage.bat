@echo off
chcp 65001 >nul
echo =========================================================================
echo    SENDING TEST GENERATION REQUEST FOR Z-IMAGE-TURBO (PORT 2504)
echo =========================================================================

curl -X POST "http://127.0.0.1:2504/api/generate" ^
  -H "Content-Type: application/json" ^
  -d "{\"positive_prompt\": \"A photorealistic cute fluffy cat sitting on a wooden bench, golden hour, high detail\", \"aspect_ratio\": \"16:9\", \"steps\": 8, \"cfg\": 1.0, \"seed\": 42}"

echo.
echo =========================================================================
pause
