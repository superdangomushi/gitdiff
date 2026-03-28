#!/usr/bin/env bash
# remove-win.sh — gitdiff uninstaller for Windows (Git Bash / MSYS2)
set -euo pipefail

INSTALL_DIR="$HOME/.local/bin"
BINARY_NAME="gitdiff"

echo "=== gitdiff uninstaller (Windows) ==="
echo ""

REMOVED=0

for target in "$INSTALL_DIR/${BINARY_NAME}.exe" "$INSTALL_DIR/$BINARY_NAME.bat"; do
    if [[ -f "$target" ]]; then
        rm "$target"
        echo "Removed: $target"
        REMOVED=1
    else
        echo "Not found (skipping): $target"
    fi
done

echo ""
if [[ $REMOVED -eq 1 ]]; then
    echo "Done! gitdiff has been uninstalled."
else
    echo "Nothing to remove. gitdiff was not installed."
fi
