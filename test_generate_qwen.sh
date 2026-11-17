#!/usr/bin/env bash
# =============================================================================
# Send test generation request for Qwen-Image-2.1 to API Server (Port 2505)
# =============================================================================

echo "========================================================================="
echo "   SENDING TEST GENERATION REQUEST FOR QWEN-IMAGE-2.1 (PORT 2505)"
echo "========================================================================="

curl -X POST "http://127.0.0.1:2505/api/generate" \
  -H "Content-Type: application/json" \
  -d '{"positive_prompt": "A photorealistic cute fluffy cat sitting on a wooden bench, golden hour, high detail", "aspect_ratio": "16:9", "steps": 30, "cfg": 6.0, "seed": 42}'

echo ""
echo "========================================================================="
