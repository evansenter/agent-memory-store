#!/bin/bash
# Install the agent memory store as a Linux systemd user service (auto-starts on login)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
SERVICE_TEMPLATE="$SCRIPT_DIR/agent-memory-store.service"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_DEST="$SERVICE_DIR/agent-memory-store.service"
SERVICE_NAME="agent-memory-store"

# Check venv exists
if [[ ! -f "$VENV_PYTHON" ]]; then
    echo "Error: Virtual environment not found at $PROJECT_DIR/.venv"
    echo "Run: uv sync"
    exit 1
fi

# Create directories if needed
mkdir -p "$SERVICE_DIR"
mkdir -p "$HOME/.claude/contrib/agent-memory-store"

# Stop existing service if running
if systemctl --user is-active "$SERVICE_NAME" &>/dev/null; then
    echo "Stopping existing service..."
    systemctl --user stop "$SERVICE_NAME"
fi

# Generate service file with correct paths
echo "Installing systemd service..."
sed -e "s|__VENV_PYTHON__|$VENV_PYTHON|g" \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    -e "s|__HOME__|$HOME|g" \
    "$SERVICE_TEMPLATE" > "$SERVICE_DEST"

# Reload systemd and start service
systemctl --user daemon-reload
echo "Starting service..."
systemctl --user enable --now "$SERVICE_NAME"

# Verify it's running
sleep 2
if systemctl --user is-active "$SERVICE_NAME" &>/dev/null; then
    echo ""
    echo "Agent Memory Store installed and running!"
    echo "  Logs: ~/.claude/contrib/agent-memory-store/agent-memory-store.log"
    echo "  Errors: ~/.claude/contrib/agent-memory-store/agent-memory-store.err"
    echo "  Status: systemctl --user status $SERVICE_NAME"
    echo ""
    echo "To uninstall: $SCRIPT_DIR/uninstall-systemd.sh"
else
    echo "Error: Service failed to start. Check logs:"
    echo "  journalctl --user -u $SERVICE_NAME"
    echo "  ~/.claude/contrib/agent-memory-store/agent-memory-store.err"
    exit 1
fi
