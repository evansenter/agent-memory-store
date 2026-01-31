#!/bin/bash
# Uninstall the agent memory store systemd user service

set -e

SERVICE_NAME="agent-memory-store"
SERVICE_FILE="$HOME/.config/systemd/user/$SERVICE_NAME.service"

echo "Stopping and disabling $SERVICE_NAME..."
systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true

if [[ -f "$SERVICE_FILE" ]]; then
    rm "$SERVICE_FILE"
    echo "Removed $SERVICE_FILE"
fi

systemctl --user daemon-reload

echo ""
echo "Agent Memory Store service uninstalled."
echo "Data remains in: ~/.claude/contrib/agent-memory-store/"
