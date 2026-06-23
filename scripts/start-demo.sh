#!/usr/bin/env bash
# XKE-15 demo launcher: amica-bridge (:8101) + Amica (:3001)
#
# Usage (no Infisical needed — uses local Claude Code Max plan auth):
#   bash scripts/start-demo.sh
#
# Bridge routes Amica → claude CLI subprocess (ADR-009). No API key required.
# Press Ctrl+C to stop both processes.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

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

# Wait for bridge to be ready (up to 10s)
for i in {1..10}; do
  if curl -sf http://localhost:8101/health > /dev/null 2>&1; then
    echo "Bridge ready."
    break
  fi
  sleep 1
done

# Start Amica (env overrides .env.local for demo)
echo "Starting Amica on :3001..."
cd "$REPO_DIR"
NEXT_PUBLIC_CHATBOT_BACKEND=chatgpt \
NEXT_PUBLIC_OPENAI_URL=http://localhost:8101 \
NEXT_PUBLIC_OPENAI_MODEL=claude-local \
NEXT_PUBLIC_OPENAI_APIKEY=local-bridge \
NEXT_PUBLIC_TTS_BACKEND=speecht5 \
NEXT_PUBLIC_SPEECHT5_SPEAKER_EMBEDDING_URL=/speecht5_speaker_embeddings/cmu_us_slt_arctic-wav-arctic_a0001.bin \
NEXT_PUBLIC_AMICA_LIFE_ENABLED=false \
npm run dev -- -p 3001 &
AMICA_PID=$!

echo ""
# Start code-server (VS Code in browser) for the live draft panel
echo "Starting code-server on :3002..."
code-server \
  --bind-addr 127.0.0.1:3002 \
  --auth none \
  ~/Desktop/github/xebia-blog &
CODE_PID=$!

# Pre-trust the workspace and set zoom — merge into existing settings
mkdir -p ~/Desktop/github/xebia-blog/.vscode
_SETTINGS=~/Desktop/github/xebia-blog/.vscode/settings.json
_BASE=$([ -f "$_SETTINGS" ] && cat "$_SETTINGS" || echo '{}')
echo "$_BASE" | jq '. + {"security.workspace.trust.enabled": false, "window.zoomLevel": -1}' > "$_SETTINGS"

echo ""
echo "Demo running:"
echo "  Amica      → http://localhost:3001"
echo "  Bridge     → http://localhost:8101/health"
echo "  code-server → http://localhost:3002"
echo "  Draft file → xebia-blog/posts/blog-draft.md"
echo "  Backend: claude subprocess (Max plan, no API key)"
echo ""
echo "Press Ctrl+C to stop."
wait "$AMICA_PID"
