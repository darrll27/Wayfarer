#!/usr/bin/env bash
# Simple dev orchestrator for macOS (zsh/bash).
# Starts backend FastAPI, Aedes broker (frontend script), and the frontend dev server.
# Usage: ./scripts/dev.sh [desktop]

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"

DESKTOP_MODE=false
if [[ ${1-} == "desktop" ]]; then
  DESKTOP_MODE=true
fi

PIDS=()
cleanup() {
  echo "Stopping background processes..."
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" || true
    fi
  done
  exit 0
}
trap cleanup INT TERM

echo "Starting backend FastAPI (uvicorn) on :8000"
cd "$ROOT_DIR"
# Run uvicorn in background so the script can continue. Uses the venv if activated.
uvicorn backend.config_api:app --port 8000 --reload &
PIDS+=("$!")

echo "Starting Aedes dev broker (will wait for backend)"
cd "$FRONTEND_DIR"
node scripts/aedes_server.js &
PIDS+=("$!")

if [ "$DESKTOP_MODE" = true ]; then
  echo "Starting frontend (desktop mode) — this will run vite and electron"
  npm run dev:desktop
else
  echo "Starting frontend dev server"
  npm run dev
fi

# If we get here (frontend exited), clean up
cleanup
