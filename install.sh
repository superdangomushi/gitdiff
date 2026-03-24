#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/bin"
SCRIPT_NAME="gitdiff"

echo "=== gitdiff installer ==="
echo ""

# ---- Python check ----
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Please install Python 3.8+."
    if command -v apt-get &>/dev/null; then
        echo "  Run: sudo apt-get install python3"
    fi
    exit 1
fi

PYTHON_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [[ "$PYTHON_MAJOR" -lt 3 ]] || { [[ "$PYTHON_MAJOR" -eq 3 ]] && [[ "$PYTHON_MINOR" -lt 8 ]]; }; then
    echo "Error: Python 3.8+ is required (found $PYTHON_VER)."
    exit 1
fi
echo "Python $PYTHON_VER found"

# ---- virtual environment ----
VENV_DIR="$HOME/.local/share/gitdiff-venv"
echo "Setting up virtual environment at $VENV_DIR..."
if ! python3 -m venv "$VENV_DIR" 2>/dev/null; then
    echo "Error: failed to create virtual environment."
    if command -v apt-get &>/dev/null; then
        echo "  On Ubuntu/Debian, run: sudo apt-get install python3-venv python3-pip"
    fi
    exit 1
fi
echo "Installing Python dependencies..."
"$VENV_DIR/bin/pip" install "textual>=0.47.0" "rich>=13.0.0" --quiet --upgrade
echo "Dependencies installed"

# ---- copy script ----
mkdir -p "$INSTALL_DIR"
DEST="$INSTALL_DIR/$SCRIPT_NAME"

# Write a wrapper that runs gitdiff.py inside the venv
cat > "$DEST" <<EOF
#!/usr/bin/env bash
exec "$VENV_DIR/bin/python3" "$SCRIPT_DIR/gitdiff.py" "\$@"
EOF
chmod +x "$DEST"
echo "Installed: $DEST"
echo ""

# ---- PATH check ----
if [[ ":$PATH:" == *":$INSTALL_DIR:"* ]]; then
    echo "✓ $INSTALL_DIR is already in PATH"
else
    echo "⚠  $INSTALL_DIR is not in your PATH."
    echo ""
    SHELL_NAME="$(basename "${SHELL:-zsh}")"
    case "$SHELL_NAME" in
        zsh)  RC="$HOME/.zshrc" ;;
        bash) RC="$HOME/.bashrc" ;;
        *)    RC="$HOME/.profile" ;;
    esac
    echo "Run the following to add it, then restart your terminal:"
    echo ""
    echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> $RC"
    echo "  source $RC"
    echo ""
fi

echo "Done!  Usage:  gitdiff <branch-a> <branch-b>"
