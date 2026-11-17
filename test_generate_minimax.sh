#!/usr/bin/env bash
# =============================================================================
# Send test generation request for MiniMax H3-Image to API Server (Port 2506)
# =============================================================================

echo "========================================================================="
echo "   SENDING TEST GENERATION REQUEST FOR MINIMAX H3-IMAGE (PORT 2506)"
echo "========================================================================="

curl -X POST "http://127.0.0.1:2506/api/generate" \
  -H "Content-Type: application/json" \
  -d '{"positive_prompt": "A photorealistic cute fluffy cat sitting on a wooden bench, golden hour, high detail", "aspect_ratio": "16:9", "steps": 6, "cfg": 1.0, "seed": 42}'

echo ""
echo "========================================================================="
