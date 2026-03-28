#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/bin"
BINARY_NAME="gitdiff"

echo "=== gitdiff installer ==="
echo ""

# ---- Go install helper ----
install_go() {
    local os arch go_latest tarball tmp_dir shell_name rc

    os="$(uname -s | tr '[:upper:]' '[:lower:]')"
    arch="$(uname -m)"
    case "$arch" in
        x86_64)          arch="amd64" ;;
        aarch64|arm64)   arch="arm64" ;;
        *) echo "Error: unsupported architecture: $arch"; exit 1 ;;
    esac

    if [[ "$os" == "darwin" ]] && command -v brew &>/dev/null; then
        echo "Installing Go via Homebrew..."
        brew install go
        return
    fi

    echo "Fetching latest Go version..."
    go_latest=$(curl -fsSL "https://go.dev/VERSION?m=text" | head -1)
    if [[ -z "$go_latest" ]]; then
        echo "Error: could not determine latest Go version. Check your internet connection."
        exit 1
    fi

    tarball="${go_latest}.${os}-${arch}.tar.gz"
    echo "Downloading https://dl.google.com/go/${tarball} ..."
    tmp_dir=$(mktemp -d)
    if ! curl -fsSL "https://dl.google.com/go/${tarball}" -o "$tmp_dir/$tarball"; then
        echo "Error: download failed."
        rm -rf "$tmp_dir"
        exit 1
    fi

    echo "Installing to /usr/local/go (requires sudo)..."
    sudo rm -rf /usr/local/go
    sudo tar -C /usr/local -xzf "$tmp_dir/$tarball"
    rm -rf "$tmp_dir"

    export PATH="/usr/local/go/bin:$PATH"

    shell_name="$(basename "${SHELL:-zsh}")"
    case "$shell_name" in
        zsh)  rc="$HOME/.zshrc" ;;
        bash) rc="$HOME/.bashrc" ;;
        *)    rc="$HOME/.profile" ;;
    esac
    echo ""
    echo "Go installed to /usr/local/go."
    echo "To make it permanent, run:"
    echo "  echo 'export PATH=\"/usr/local/go/bin:\$PATH\"' >> $rc"
    echo "  source $rc"
    echo ""
}

# ---- Go check ----
if ! command -v go &>/dev/null; then
    echo "Go not found. Installing automatically..."
    install_go
fi

GO_VER=$(go version | awk '{print $3}' | sed 's/go//')
GO_MAJOR=$(echo "$GO_VER" | cut -d. -f1)
GO_MINOR=$(echo "$GO_VER" | cut -d. -f2)
if [[ "$GO_MAJOR" -lt 1 ]] || { [[ "$GO_MAJOR" -eq 1 ]] && [[ "$GO_MINOR" -lt 21 ]]; }; then
    echo "Go 1.21+ is required (found $GO_VER). Upgrading automatically..."
    install_go
fi
echo "Go $GO_VER found"

# ---- fetch dependencies & build ----
echo "Fetching dependencies..."
(cd "$SCRIPT_DIR" && go mod tidy)
echo "Building..."
(cd "$SCRIPT_DIR" && go build -o "$SCRIPT_DIR/$BINARY_NAME" .)
echo "Build successful"

# ---- install binary ----
mkdir -p "$INSTALL_DIR"
DEST="$INSTALL_DIR/$BINARY_NAME"
cp "$SCRIPT_DIR/$BINARY_NAME" "$DEST"
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

echo "Done!  Usage:  gitdiff <branch-a> [<branch-b>]"
