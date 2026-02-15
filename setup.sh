#!/usr/bin/env bash
# Setup script for Claude Code Session History (Linux / macOS)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m virtualenv "$VENV_DIR"
fi

# Activate and install dependencies
source "$VENV_DIR/bin/activate"
echo "Installing Python dependencies..."
pip install PyQt6 PyWinCtl

# Run setup (hook registration) using the venv Python
python "$SCRIPT_DIR/setup.py"

echo ""
echo "Virtual environment created at: $VENV_DIR"
echo "To launch the GUI, run:"
echo "  $VENV_DIR/bin/python $SCRIPT_DIR/review_gui.py"
