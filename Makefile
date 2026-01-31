.PHONY: check fmt lint test clean install-server install-client uninstall dev venv

# Run all quality gates
check: fmt lint test

# Check formatting with ruff
fmt:
	ruff format --check .

# Run linter
lint:
	ruff check .

# Run tests
test:
	pytest tests/ -v

# Clean build artifacts
clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Create virtual environment
venv:
	uv sync

# Install with dev dependencies
dev:
	uv sync --extra dev

# Server installation (local machine hosting the memory store)
install-server: venv
	@echo "Installing server..."
	uv sync
	@echo ""
	@if [ "$$(uname)" = "Darwin" ]; then \
		echo "Installing LaunchAgent (macOS)..."; \
		./scripts/install-launchagent.sh; \
	else \
		echo "Installing systemd service (Linux)..."; \
		./scripts/install-systemd.sh; \
	fi
	@echo ""
	@echo "Adding to Claude Code..."
	@CLAUDE_CMD=$$(command -v claude || echo "$$HOME/.local/bin/claude"); \
	if [ -x "$$CLAUDE_CMD" ]; then \
		$$CLAUDE_CMD mcp add --transport http --scope user agent-memory-store http://localhost:8082/mcp 2>/dev/null && \
			echo "Added agent-memory-store to Claude Code" || \
			echo "agent-memory-store already configured in Claude Code"; \
	else \
		echo "Note: claude not found. Run manually:"; \
		echo "  claude mcp add --transport http --scope user agent-memory-store http://localhost:8082/mcp"; \
	fi
	@echo ""
	@echo "Server installation complete!"

# Client installation (connects to remote memory store)
install-client:
	@if [ -z "$(REMOTE_URL)" ]; then \
		echo "Error: REMOTE_URL is required"; \
		echo "Usage: make install-client REMOTE_URL=https://your-server.tailnet.ts.net/agent-memory-store/mcp"; \
		exit 1; \
	fi
	@echo "Installing client (connecting to $(REMOTE_URL))..."
	@CLAUDE_CMD=$$(command -v claude || echo "$$HOME/.local/bin/claude"); \
	if [ -x "$$CLAUDE_CMD" ]; then \
		$$CLAUDE_CMD mcp remove --scope user agent-memory-store 2>/dev/null || true; \
		$$CLAUDE_CMD mcp add --transport http --scope user agent-memory-store "$(REMOTE_URL)" && \
			echo "Added agent-memory-store to Claude Code ($(REMOTE_URL))"; \
	else \
		echo "Note: claude not found. Run manually:"; \
		echo "  claude mcp add --transport http --scope user agent-memory-store $(REMOTE_URL)"; \
	fi

# Uninstall
uninstall:
	@echo "Uninstalling..."
	@if [ "$$(uname)" = "Darwin" ]; then \
		./scripts/uninstall-launchagent.sh; \
	else \
		./scripts/uninstall-systemd.sh; \
	fi
	@CLAUDE_CMD=$$(command -v claude || echo "$$HOME/.local/bin/claude"); \
	if [ -x "$$CLAUDE_CMD" ]; then \
		$$CLAUDE_CMD mcp remove --scope user agent-memory-store 2>/dev/null || true; \
	fi
	@echo "Uninstall complete!"
