#!/bin/bash
set -e

echo "========================================================"
echo "       Starting LocalLeads Kit v1.0.2..."
echo "========================================================"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Runtime and cache isolated in ~/.localleadskit
KIT_RUNTIME_DIR="$HOME/.localleadskit"
mkdir -p "$KIT_RUNTIME_DIR"
export UV_CACHE_DIR="$KIT_RUNTIME_DIR/uv-cache"
export UV_PYTHON_INSTALL_DIR="$KIT_RUNTIME_DIR/python"
VENV_DIR="$KIT_RUNTIME_DIR/venv"
BIN_DIR="$KIT_RUNTIME_DIR/bin"
mkdir -p "$BIN_DIR"

UV_VERSION="0.6.5"

# 1. Look for uv executable in runtime bin or kit folder
UV_BIN=""
if [ -f "$BIN_DIR/uv" ]; then
    UV_BIN="$BIN_DIR/uv"
elif [ -f "$SCRIPT_DIR/bin/uv" ]; then
    UV_BIN="$SCRIPT_DIR/bin/uv"
elif [ -f "$SCRIPT_DIR/uv" ]; then
    UV_BIN="$SCRIPT_DIR/uv"
fi

# 2. If missing, detect OS/CPU, download pinned uv, and verify SHA256
if [ -z "$UV_BIN" ]; then
    OS="$(uname -s)"
    ARCH="$(uname -m)"

    if [ "$OS" = "Darwin" ]; then
        if [ "$ARCH" = "arm64" ]; then
            UV_TARGET="uv-aarch64-apple-darwin.tar.gz"
            EXPECTED_HASH="4952c6275778fbc7e5cf6b5739ffd944c47063134d6ea43a7037b0a028ef771e"
        else
            UV_TARGET="uv-x86_64-apple-darwin.tar.gz"
            EXPECTED_HASH="d336d862694e1c36afea55eb15f5df02aa77c04a168b781df515d641e23285f0"
        fi
    elif [ "$OS" = "Linux" ]; then
        if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
            UV_TARGET="uv-aarch64-unknown-linux-gnu.tar.gz"
            EXPECTED_HASH="ebf0707ab949b948ad14250ed93f968fec954e20d12ce6bc9fce74b0ce7e4900"
        else
            UV_TARGET="uv-x86_64-unknown-linux-gnu.tar.gz"
            EXPECTED_HASH="8fc9895719a1291ecd193cb86f9282ff3649cef797d29eacc74c4f573aab1e2f"
        fi
    else
        echo "[ERROR] Unsupported operating system: $OS ($ARCH)"
        exit 1
    fi

    UV_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${UV_TARGET}"
    ARCHIVE_PATH="$KIT_RUNTIME_DIR/uv_download.tar.gz"

    echo "[1/4] Runtime manager (uv) not found."
    echo "      Downloading verified official uv v${UV_VERSION} for ${OS} (${ARCH})..."

    rm -f "$ARCHIVE_PATH"
    if command -v curl &> /dev/null; then
        curl -fL "$UV_URL" -o "$ARCHIVE_PATH" --silent --show-error
    elif command -v wget &> /dev/null; then
        wget -q -O "$ARCHIVE_PATH" "$UV_URL"
    else
        echo "[ERROR] Neither curl nor wget found. Please install curl to download dependencies."
        exit 1
    fi

    echo "      Verifying cryptographic SHA256 checksum..."
    ACTUAL_HASH=""
    if command -v shasum &> /dev/null; then
        ACTUAL_HASH="$(shasum -a 256 "$ARCHIVE_PATH" | awk '{print $1}')"
    elif command -v sha256sum &> /dev/null; then
        ACTUAL_HASH="$(sha256sum "$ARCHIVE_PATH" | awk '{print $1}')"
    else
        echo "[ERROR] Neither shasum nor sha256sum available to verify integrity."
        rm -f "$ARCHIVE_PATH"
        exit 1
    fi

    if [ "$ACTUAL_HASH" != "$EXPECTED_HASH" ]; then
        echo ""
        echo "[ERROR] Cryptographic checksum verification failed!"
        echo "Expected: $EXPECTED_HASH"
        echo "Actual:   $ACTUAL_HASH"
        echo "The downloaded archive may be corrupted or compromised. Aborting."
        rm -f "$ARCHIVE_PATH"
        exit 1
    fi
    echo "      Checksum verified successfully."

    tar -xzf "$ARCHIVE_PATH" -C "$BIN_DIR" --strip-components=1 uv 2>/dev/null || tar -xzf "$ARCHIVE_PATH" -C "$BIN_DIR"
    chmod +x "$BIN_DIR/uv"
    rm -f "$ARCHIVE_PATH"

    UV_BIN="$BIN_DIR/uv"
fi

# 3. Ensure Streamlit credentials exist to prevent first-run prompt
mkdir -p "$HOME/.streamlit"
if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
    printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
fi

# 4. Create isolated Python 3.11 virtual environment under ~/.localleadskit if missing
if [ ! -d "$VENV_DIR" ]; then
    echo "[2/4] Setting up isolated Python 3.11 runtime in $KIT_RUNTIME_DIR..."
    "$UV_BIN" venv "$VENV_DIR" --python 3.11
fi

# 5. Install / sync dependencies into runtime venv
echo "[3/4] Verifying dependencies..."
"$UV_BIN" pip install --python "$VENV_DIR" -r "$SCRIPT_DIR/requirements.txt" --quiet

# 6. Launch LocalLeads Kit via uv in runtime venv (CWD remains kit folder for user data)
echo "[4/4] Launching LocalLeads Kit in your default browser..."
echo ""
"$UV_BIN" run --python "$VENV_DIR" streamlit run "$SCRIPT_DIR/app.py"
