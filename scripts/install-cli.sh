#!/usr/bin/env bash
# Install the memory CLI tool globally using uv or pipx

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Installing agent-memory-store CLI..."

# Prefer uv if available, fall back to pipx
if command -v uv &> /dev/null; then
    echo "Using uv..."
    uv tool install "$PROJECT_DIR"
elif command -v pipx &> /dev/null; then
    echo "Using pipx..."
    pipx install "$PROJECT_DIR"
else
    echo "Error: Neither 'uv' nor 'pipx' found."
    echo "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "Or install pipx: python3 -m pip install --user pipx"
    exit 1
fi

echo ""
echo "✓ Installed! Run 'memory --help' to get started."
echo ""
echo "Examples:"
echo "  memory store my-key 'my value' --tags important,work"
echo "  memory recall my-key"
echo "  memory recall -s 'search query'"
echo "  memory list --limit 10"
echo "  memory forget my-key"
