#!/usr/bin/env bash
# create_venv.sh
# Create (or recreate) the .wayfarer_venv virtual environment at the repository root,
# activate it, upgrade packaging tools, and install the local package so `wayfarer` CLI is available.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$BASE_DIR/.wayfarer_venv"
PYTHON_CMD="${1:-python3}"

echo "Repository base: $BASE_DIR"
echo "Using python: $PYTHON_CMD"

# Check python exists
if ! command -v "$PYTHON_CMD" >/dev/null 2>&1; then
  echo "ERROR: $PYTHON_CMD not found on PATH. Provide path or install it." >&2
  exit 2
fi

# Create venv
if [ -d "$VENV" ]; then
  echo ".wayfarer_venv already exists at $VENV"
  read -r -p "Remove and recreate venv? [y/N] " REPLY
  if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    echo "Removing existing venv..."
    rm -rf "$VENV"
  else
    echo "Keeping existing venv. Will attempt to use it." 
  fi
fi

echo "Creating virtualenv at $VENV using $PYTHON_CMD"
"$PYTHON_CMD" -m venv "$VENV"

# Activate and install
# Use a subshell so we don't pollute the caller environment
(
  set -euo pipefail
  source "$VENV/bin/activate"
  echo "Upgrading pip"
  pip install --upgrade pip

  # Prefer requirements.txt if present
  if [ -f "$BASE_DIR/requirements.txt" ]; then
    echo "Installing from requirements.txt"
    pip install -r "$BASE_DIR/requirements.txt"
  else
    # Install editable package so the `wayfarer` CLI entry point is available
    echo "No requirements.txt found; installing the local package in editable mode"
    pip install -e "$BASE_DIR"
  fi
)

echo "Virtualenv created and packages installed. To activate it, run:"
echo "  source \"$VENV/bin/activate\""
echo "Then you can run:"
echo "  wayfarer -c examples/wayfarer.config.houston.yaml"

echo "Done."