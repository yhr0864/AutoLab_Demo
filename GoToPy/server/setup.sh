#!/usr/bin/env bash
#
# setup.sh — Create virtual environment and install dependencies
#
# Usage: bash setup.sh
# Then activate with: source venv/Scripts/activate  (Git Bash)
#                  or: venv\Scripts\activate         (PowerShell / CMD)

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT_DIR/venv"

echo "=== Creating virtual environment ==="
python -m venv "$VENV_DIR"

# Activate (Git Bash / Linux / macOS)
source "$VENV_DIR/Scripts/activate"

echo "=== Installing dependencies ==="
pip install -r "$ROOT_DIR/requirements.txt"

echo ""
echo "=== Done! ==="
echo "Virtual environment: $VENV_DIR"
echo ""
echo "To activate manually:"
echo "  Git Bash:  source server/venv/Scripts/activate"
echo "  PowerShell: server\\venv\\Scripts\\activate"
echo "  CMD:        server\\venv\\Scripts\\activate.bat"