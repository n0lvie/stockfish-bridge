#!/bin/bash
# Stockfish Bridge - Setup Script for Termux
# Run this script in Termux to install all dependencies

set -e

echo "╔══════════════════════════════════════════════╗"
echo "║     Stockfish Bridge - Termux Setup           ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Update packages
echo "[1/4] Updating packages..."
pkg update -y && pkg upgrade -y

# Install required packages
echo "[2/4] Installing Python and Stockfish..."
pkg install -y python stockfish

# Install Python dependencies
echo "[3/4] Installing Python dependencies..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pip install -r "$SCRIPT_DIR/server/requirements.txt"

# Verify installation
echo "[4/4] Verifying installation..."
echo ""

STOCKFISH_PATH=$(which stockfish 2>/dev/null || echo "NOT FOUND")
PYTHON_VERSION=$(python --version 2>&1)

echo "  Python:     $PYTHON_VERSION"
echo "  Stockfish:  $STOCKFISH_PATH"

if [ "$STOCKFISH_PATH" = "NOT FOUND" ]; then
    echo ""
    echo "⚠ Stockfish not found in PATH!"
    echo "  Try: pkg install stockfish"
    exit 1
fi

# Get Stockfish version
SF_VERSION=$($STOCKFISH_PATH <<< "quit" 2>&1 | head -1)
echo "  Version:    $SF_VERSION"

echo ""
echo "✅ Setup complete!"
echo ""
echo "To start the bridge server:"
echo "  python $SCRIPT_DIR/server/bridge.py"
echo ""
echo "For custom settings:"
echo "  python $SCRIPT_DIR/server/bridge.py --threads 4 --hash 512"
echo ""
echo "To keep Termux running in background:"
echo "  termux-wake-lock"
echo ""
