#!/usr/bin/env bash
# install-win.sh — gitdiff installer for Windows (Git Bash / MSYS2)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/bin"
SCRIPT_NAME="gitdiff"

echo "=== gitdiff installer (Windows) ==="
echo ""

# ---- Python check ----
# Windows usually has 'python' instead of 'python3'
PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo "Error: python not found. Please install Python 3.8+ from https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VER=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$("$PYTHON" -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$("$PYTHON" -c 'import sys; print(sys.version_info.minor)')
if [[ "$PYTHON_MAJOR" -lt 3 ]] || { [[ "$PYTHON_MAJOR" -eq 3 ]] && [[ "$PYTHON_MINOR" -lt 8 ]]; }; then
    echo "Error: Python 3.8+ is required (found $PYTHON_VER)."
    exit 1
fi
echo "Python $PYTHON_VER found ($PYTHON)"

# ---- virtual environment ----
VENV_DIR="$HOME/.local/share/gitdiff-venv"
echo "Setting up virtual environment at $VENV_DIR..."
if ! "$PYTHON" -m venv "$VENV_DIR" 2>/dev/null; then
    echo "Error: failed to create virtual environment."
    echo "  Make sure 'pip' and 'venv' are available:"
    echo "    $PYTHON -m ensurepip"
    exit 1
fi

# Windows venv puts executables in Scripts/, not bin/
VENV_PIP="$VENV_DIR/Scripts/pip"
VENV_PYTHON="$VENV_DIR/Scripts/python"
if [[ ! -f "$VENV_PIP" ]]; then
    # Fallback for environments that use bin/
    VENV_PIP="$VENV_DIR/bin/pip"
    VENV_PYTHON="$VENV_DIR/bin/python"
fi

echo "Installing Python dependencies..."
"$VENV_PIP" install "textual>=0.47.0" "rich>=13.0.0" --quiet --upgrade
echo "Dependencies installed"

# ---- create wrapper script (bash) ----
mkdir -p "$INSTALL_DIR"
DEST="$INSTALL_DIR/$SCRIPT_NAME"

# Convert SCRIPT_DIR to a Windows-compatible path for the Python interpreter
SCRIPT_DIR_WIN="$(cd "$SCRIPT_DIR" && pwd -W 2>/dev/null || pwd)"

cat > "$DEST" <<EOF
#!/usr/bin/env bash
exec "$VENV_PYTHON" "$SCRIPT_DIR/gitdiff.py" "\$@"
EOF
chmod +x "$DEST"
echo "Installed: $DEST"

# ---- create .bat wrapper for CMD / PowerShell ----
# Convert paths to Windows-style for the .bat file
VENV_PYTHON_WIN="$(cd "$(dirname "$VENV_PYTHON")" && pwd -W 2>/dev/null || pwd)/$(basename "$VENV_PYTHON")"
GITDIFF_PY_WIN="$SCRIPT_DIR_WIN/gitdiff.py"

BAT_DEST="$INSTALL_DIR/$SCRIPT_NAME.bat"
cat > "$BAT_DEST" <<EOF
@echo off
"$(echo "$VENV_PYTHON_WIN" | sed 's|/|\\|g')" "$(echo "$GITDIFF_PY_WIN" | sed 's|/|\\|g')" %*
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
    # Show Windows-style path for CMD/PowerShell users
    WIN_INSTALL_DIR="$(cd "$INSTALL_DIR" && pwd -W 2>/dev/null || echo "$INSTALL_DIR")"
    echo "For CMD / PowerShell, add to your system PATH:"
    echo ""
    echo "  $(echo "$WIN_INSTALL_DIR" | sed 's|/|\\|g')"
    echo ""
fi

echo "Done!  Usage:  gitdiff <branch-a> [<branch-b>]"
