"""HTTP MCP server wrapper for agent-memory-store."""

import json
import os
from pathlib import Path

from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .server import server
from .storage import MemoryStorage

# Initialize storage
DB_PATH = os.environ.get(
    "MEMORY_STORE_DB",
    Path.home() / ".claude" / "contrib" / "agent-memory-store" / "memories.db",
)
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


class TailscaleAuthMiddleware:
    """Require Tailscale identity for non-localhost connections."""

    TAILSCALE_USER_HEADER = b"tailscale-user-login"
    TRUSTED_IPS = ("127.0.0.1", "::1", "localhost")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Trust localhost
        client_ip = scope.get("client", ("", 0))[0]
        if client_ip in self.TRUSTED_IPS:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        if not headers.get(self.TAILSCALE_USER_HEADER):
            response = JSONResponse(
                {"error": "Unauthorized", "message": "Tailscale identity required"},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


# SSE transport for MCP
sse = SseServerTransport("/mcp/")


async def handle_sse(request: Request) -> Response:
    """Handle SSE connections for MCP."""
    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await server.run(
            streams[0], streams[1], server.create_initialization_options()
        )
    return Response()


async def handle_mcp_post(request: Request) -> Response:
    """Handle POST requests for MCP (stateless HTTP transport)."""
    body = await request.body()
    
    # Parse JSON-RPC request
    try:
        rpc_request = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    # Handle via server
    # For now, return method not supported - full implementation would route to server
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": rpc_request.get("id"),
        "error": {"code": -32601, "message": "Use SSE transport at /mcp/"},
    })


async def health(request: Request) -> JSONResponse:
    """Health check endpoint."""
    storage = MemoryStorage(DB_PATH)
    count = len(storage.list_memories(limit=1000))
    return JSONResponse({
        "status": "healthy",
        "service": "agent-memory-store",
        "memories_count": count,
    })


# Build app
routes = [
    Route("/health", health, methods=["GET"]),
    Route("/mcp", handle_mcp_post, methods=["POST"]),
    Route("/mcp/", handle_sse, methods=["GET"]),
]

app = Starlette(
    routes=routes,
    middleware=[Middleware(TailscaleAuthMiddleware)] if not os.environ.get("AUTH_DISABLED") else [],
)
