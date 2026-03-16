#!/usr/bin/env bash
# Simple dev orchestrator for Linux/macOS (zsh/bash).
# Starts backend FastAPI, Aedes broker (frontend script), and the frontend dev server.
# Usage: ./scripts/dev.sh [desktop|backend-only]

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
LOG_DIR="$ROOT_DIR/logs"
VENV_DIR="$ROOT_DIR/.venv"
REQ_FILE="$ROOT_DIR/requirements.txt"
REQ_HASH_FILE="$VENV_DIR/.requirements.sha256"

mkdir -p "$LOG_DIR"

timestamp_pipe() {
  local logfile="$1"
  while IFS= read -r line; do
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$line" >> "$logfile"
  done
}

ensure_backend_venv() {
  if [[ ! -f "$REQ_FILE" ]]; then
    echo "[dev] missing requirements file: $REQ_FILE"
    exit 1
  fi

  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    echo "[dev] creating backend venv at $VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi

  local req_hash=""
  local need_install=0
  req_hash="$($VENV_DIR/bin/python - <<'PY'
import hashlib
from pathlib import Path

print(hashlib.sha256(Path('requirements.txt').read_bytes()).hexdigest())
PY
)"

  if [[ ! -f "$REQ_HASH_FILE" ]]; then
    need_install=1
  elif [[ "$(cat "$REQ_HASH_FILE")" != "$req_hash" ]]; then
    need_install=1
  fi

  # Ensure critical runtime packages are importable even if the hash file exists.
  if ! "$VENV_DIR/bin/python" -c "import fastapi, uvicorn, yaml, paho.mqtt.client" >/dev/null 2>&1; then
    need_install=1
  fi

  if [[ "$need_install" -eq 1 ]]; then
    echo "[dev] installing backend dependencies from requirements.txt"
    "$VENV_DIR/bin/python" -m pip install --upgrade pip
    "$VENV_DIR/bin/python" -m pip install -r "$REQ_FILE"
    printf '%s\n' "$req_hash" > "$REQ_HASH_FILE"
  else
    echo "[dev] backend venv is up to date"
  fi
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
ensure_backend_venv
# Run uvicorn in background so the script can continue.
UVICORN_ARGS=(backend.config_api:app --port 8000)
if [[ "$DESKTOP_MODE" == "false" ]]; then
  UVICORN_ARGS+=(--reload)
else
  echo "[dev] desktop mode: backend reload disabled to reduce file watcher usage"
fi
echo "[dev] backend log: $LOG_DIR/api.log"
("$VENV_DIR/bin/python" -m uvicorn "${UVICORN_ARGS[@]}" 2>&1 | timestamp_pipe "$LOG_DIR/api.log") &
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
