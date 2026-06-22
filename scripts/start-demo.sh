#!/usr/bin/env bash
# XKE-15 demo launcher: starts amica-bridge on :8101 + Amica on :3001
#
# Usage:
#   ~/infisical-run.sh bash scripts/start-demo.sh
#
# The ANTHROPIC_API_KEY must already be in the environment (infisical-run.sh injects it).
# Press Ctrl+C to stop both processes.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "ERROR: ANTHROPIC_API_KEY is not set."
  echo "Run with: ~/infisical-run.sh bash scripts/start-demo.sh"
  exit 1
fi

cleanup() {
  echo ""
  echo "Stopping bridge and Amica..."
  kill "$BRIDGE_PID" "$AMICA_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Start the bridge
echo "Starting amica-bridge on :8101..."
uv run "$SCRIPT_DIR/amica-bridge.py" &
BRIDGE_PID=$!

# Wait for bridge to be ready
for i in {1..10}; do
  if curl -sf http://localhost:8101/health > /dev/null 2>&1; then
    echo "Bridge ready."
    break
  fi
  sleep 1
done

# Start Amica with bridge config (overrides .env.local for the demo vars)
echo "Starting Amica on :3001..."
cd "$REPO_DIR"
NEXT_PUBLIC_CHATBOT_BACKEND=chatgpt \
NEXT_PUBLIC_OPENAI_URL=http://localhost:8101 \
NEXT_PUBLIC_OPENAI_MODEL=claude-haiku-4-5-20251001 \
NEXT_PUBLIC_OPENAI_APIKEY=local-bridge \
npm run dev -- -p 3001 &
AMICA_PID=$!

echo ""
echo "Demo running:"
echo "  Amica  → http://localhost:3001"
echo "  Bridge → http://localhost:8101/health"
echo ""
echo "Press Ctrl+C to stop."
wait "$AMICA_PID"
