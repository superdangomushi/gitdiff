#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.local/bin"
BINARY_NAME="gitdiff"

echo "=== gitdiff uninstaller ==="
echo ""

REMOVED=0

DEST="$INSTALL_DIR/$BINARY_NAME"
if [[ -f "$DEST" ]]; then
    rm "$DEST"
    echo "Removed: $DEST"
    REMOVED=1
else
    echo "Not found (skipping): $DEST"
fi

echo ""
if [[ $REMOVED -eq 1 ]]; then
    echo "Done! gitdiff has been uninstalled."
else
    echo "Nothing to remove. gitdiff was not installed."
fi
