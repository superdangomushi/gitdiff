#!/usr/bin/env bash
# remove-win.sh — gitdiff uninstaller for Windows (Git Bash / MSYS2)
set -euo pipefail

INSTALL_DIR="$HOME/.local/bin"
SCRIPT_NAME="gitdiff"
VENV_DIR="$HOME/.local/share/gitdiff-venv"

echo "=== gitdiff uninstaller (Windows) ==="
echo ""

REMOVED=0

# ---- remove wrapper scripts ----
DEST="$INSTALL_DIR/$SCRIPT_NAME"
if [[ -f "$DEST" ]]; then
    rm "$DEST"
    echo "Removed: $DEST"
    REMOVED=1
else
    echo "Not found (skipping): $DEST"
fi

BAT_DEST="$INSTALL_DIR/$SCRIPT_NAME.bat"
if [[ -f "$BAT_DEST" ]]; then
    rm "$BAT_DEST"
    echo "Removed: $BAT_DEST"
    REMOVED=1
else
    echo "Not found (skipping): $BAT_DEST"
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
