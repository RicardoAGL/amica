#!/usr/bin/env bash
# amica-local — restart the bridge in local-LLM fallback mode.
# Use when Anthropic is unreachable. Requires llama.cpp server on :8080.
#
# Usage:
#   ./scripts/amica-local.sh                  # default: qwen3 on localhost:8080
#   AMICA_LOCAL_MODEL=llama3 ./scripts/amica-local.sh
#
# To confirm llama.cpp is running:
#   curl -sf http://localhost:8080/health | jq .
#
# To restore normal (claude) mode:
#   kill $(lsof -ti :8101) && uv run scripts/amica-bridge.py

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Kill whatever is on the bridge port
kill "$(lsof -ti :8101)" 2>/dev/null || true
sleep 1

echo "[amica-local] Starting bridge → local llama.cpp (${AMICA_LOCAL_MODEL:-qwen3})"
cd "$REPO_DIR"
AMICA_BACKEND=local \
AMICA_LOCAL_URL="${AMICA_LOCAL_URL:-http://localhost:8080/v1/chat/completions}" \
AMICA_LOCAL_MODEL="${AMICA_LOCAL_MODEL:-qwen3}" \
uv run scripts/amica-bridge.py
