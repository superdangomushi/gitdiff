#!/usr/bin/env bash
# install-win.sh — gitdiff installer for Windows (Git Bash / MSYS2)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/bin"
BINARY_NAME="gitdiff"

echo "=== gitdiff installer (Windows) ==="
echo ""

# ---- Go check ----
if ! command -v go &>/dev/null; then
    echo "Error: go not found. Please install Go 1.21+ from https://go.dev/dl/"
    exit 1
fi

GO_VER=$(go version | awk '{print $3}' | sed 's/go//')
GO_MAJOR=$(echo "$GO_VER" | cut -d. -f1)
GO_MINOR=$(echo "$GO_VER" | cut -d. -f2)
if [[ "$GO_MAJOR" -lt 1 ]] || { [[ "$GO_MAJOR" -eq 1 ]] && [[ "$GO_MINOR" -lt 21 ]]; }; then
    echo "Error: Go 1.21+ is required (found $GO_VER)."
    exit 1
fi
echo "Go $GO_VER found"

# ---- fetch dependencies & build ----
echo "Fetching dependencies..."
(cd "$SCRIPT_DIR" && go mod tidy)
echo "Building..."
(cd "$SCRIPT_DIR" && go build -o "$SCRIPT_DIR/${BINARY_NAME}.exe" .)
echo "Build successful"

# ---- install binary ----
mkdir -p "$INSTALL_DIR"
DEST="$INSTALL_DIR/${BINARY_NAME}.exe"
cp "$SCRIPT_DIR/${BINARY_NAME}.exe" "$DEST"
chmod +x "$DEST"
echo "Installed: $DEST"

# ---- create .bat wrapper for CMD / PowerShell ----
DEST_WIN="$(cd "$INSTALL_DIR" && pwd -W 2>/dev/null || echo "$INSTALL_DIR")\\${BINARY_NAME}.exe"
BAT_DEST="$INSTALL_DIR/$BINARY_NAME.bat"
cat > "$BAT_DEST" <<EOF
@echo off
"$(echo "$DEST_WIN" | sed 's|/|\\|g')" %*
EOF
echo "Installed: $BAT_DEST"
echo ""

# ---- PATH check ----
if [[ ":$PATH:" == *":$INSTALL_DIR:"* ]]; then
    echo "✓ $INSTALL_DIR is already in PATH"
else
    echo "⚠  $INSTALL_DIR is not in your PATH."
    echo ""
    echo "For Git Bash, add to ~/.bashrc:"
    echo ""
    echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
    echo "  source ~/.bashrc"
    echo ""
    WIN_INSTALL_DIR="$(cd "$INSTALL_DIR" && pwd -W 2>/dev/null || echo "$INSTALL_DIR")"
    echo "For CMD / PowerShell, add to your system PATH:"
    echo ""
    echo "  $(echo "$WIN_INSTALL_DIR" | sed 's|/|\\|g')"
    echo ""
fi

echo "Done!  Usage:  gitdiff <branch-a> [<branch-b>]"
