#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.local/bin"
SCRIPT_NAME="gitdiff"
VENV_DIR="$HOME/.local/share/gitdiff-venv"

echo "=== gitdiff uninstaller ==="
echo ""

REMOVED=0

# ---- remove wrapper script ----
DEST="$INSTALL_DIR/$SCRIPT_NAME"
if [[ -f "$DEST" ]]; then
    rm "$DEST"
    echo "Removed: $DEST"
    REMOVED=1
else
    echo "Not found (skipping): $DEST"
fi

# ---- remove virtual environment ----
if [[ -d "$VENV_DIR" ]]; then
    rm -rf "$VENV_DIR"
    echo "Removed: $VENV_DIR"
    REMOVED=1
else
    echo "Not found (skipping): $VENV_DIR"
fi

echo ""
if [[ $REMOVED -eq 1 ]]; then
    echo "Done! gitdiff has been uninstalled."
else
    echo "Nothing to remove. gitdiff was not installed."
fi
