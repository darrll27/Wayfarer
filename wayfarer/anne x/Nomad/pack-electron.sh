#!/usr/bin/env bash
# Prototype packaging script for Nomad (macOS-focused)
# Steps performed:
# 1. Build Python backend into a single executable using PyInstaller
# 2. Build frontend (Vite) into `frontend/dist`
# 3. Run electron-builder to create a macOS app
#
# Requirements on the machine:
# - Python 3.11/3.12 and a virtualenv with PyInstaller installed (pip install pyinstaller)
# - Node >= 22.12.0 and npm
# - In `frontend`: electron-builder devDependency (installed by npm)
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Nomad packaging script -- root: $ROOT_DIR"

cd "$ROOT_DIR"

echo "1) Building Python backend (PyInstaller)..."
if [ -f .venv/bin/activate ]; then
  # activate venv if present
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if ! command -v pyinstaller >/dev/null 2>&1; then
  echo "pyinstaller not found in PATH or current venv. Install it with: pip install pyinstaller"
  exit 1
fi

# Clean previous build artifacts
rm -rf dist backend_build build nomad-backend.spec

# Use the src entry that starts the uvicorn server (src/nomad/main.py). If you prefer a small launcher
# script that simply launches the app process, point PyInstaller at that script instead.
pyinstaller --onefile --name nomad-backend src/nomad/main.py

echo "Python backend built: dist/nomad-backend"

echo "2) Building frontend (Vite)..."
cd "$ROOT_DIR/frontend"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found; please install Node/npm"
  exit 1
fi

npm install --silent
npm run build

echo "Frontend build complete: frontend/dist"

echo "3) Running electron-builder to produce a macOS app..."
# electron-builder expects to find the frontend `dist` and the electron main file at the frontend root
# Ensure electron-builder is installed in the frontend devDependencies
if [ ! -f node_modules/.bin/electron-builder ]; then
  echo "Installing electron-builder locally in frontend..."
  npm install --no-audit --no-fund --silent electron-builder@^24.6.0
fi

# Copy backend executable next to frontend package (so build.extraResources can include it)
cp -v "$ROOT_DIR/dist/nomad-backend" "$ROOT_DIR/frontend/nomad-backend" || true

cd "$ROOT_DIR/frontend"

echo "Running electron-builder..."
npx electron-builder --mac --x64

echo "Packaging finished. Artifacts are in frontend/release (or as printed by electron-builder)."

echo "Done."
