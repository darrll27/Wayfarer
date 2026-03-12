#!/usr/bin/env bash
# Simple dev orchestrator for macOS (zsh/bash).
# Starts backend FastAPI, Aedes broker (frontend script), and the frontend dev server.
# Usage: ./scripts/dev.sh [desktop|backend-only]

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
LOG_DIR="$ROOT_DIR/logs"

mkdir -p "$LOG_DIR"

timestamp_pipe() {
  local logfile="$1"
  while IFS= read -r line; do
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$line" >> "$logfile"
  done
}

DESKTOP_MODE=false
BACKEND_ONLY=false
if [[ ${1-} == "desktop" ]]; then
  DESKTOP_MODE=true
elif [[ ${1-} == "backend-only" ]]; then
  BACKEND_ONLY=true
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
echo "[dev] backend log: $LOG_DIR/api.log"
(uvicorn backend.config_api:app --port 8000 --reload 2>&1 | timestamp_pipe "$LOG_DIR/api.log") &
PIDS+=("$!")

echo "Starting Aedes dev broker (will wait for backend)"
cd "$FRONTEND_DIR"
echo "[dev] broker log: $LOG_DIR/aedes.log"
(node scripts/aedes_server.js 2>&1 | timestamp_pipe "$LOG_DIR/aedes.log") &
PIDS+=("$!")

if [ "$BACKEND_ONLY" = true ]; then
  echo "Backend-only mode: started backend and broker, waiting..."
  # Wait indefinitely
  wait
elif [ "$DESKTOP_MODE" = true ]; then
  echo "Starting frontend (desktop mode) — this will run vite and electron"
  echo "[dev] frontend log: $LOG_DIR/frontend.log"
  npm run dev:desktop 2>&1 | timestamp_pipe "$LOG_DIR/frontend.log"
else
  echo "Starting frontend dev server"
  echo "[dev] frontend log: $LOG_DIR/frontend.log"
  npm run dev 2>&1 | timestamp_pipe "$LOG_DIR/frontend.log"
fi

# If we get here (frontend exited), clean up
cleanup
