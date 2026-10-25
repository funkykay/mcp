"""One upstream REST/storage instance + SDK MCP transport; no upstream patches.

12.3.1's REST MCP shim injects X-Agent-ID into read filters. The SDK transport
keeps caller attribution in context instead, preserving shared cross-agent reads.
"""
import fcntl
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
lock = open(os.environ.get('MEMORY_LOCK_PATH', str(ROOT / 'runtime/server.lock')), 'a+')
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit('A central memory server already owns the lock')

# Bind before importing ML: an occupied port must not load another model.
import socket
port = int(os.environ.get('MEMORY_PORT', '8000'))
sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('127.0.0.1', port))

from contextlib import asynccontextmanager
import asyncio
import uvicorn
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
import mcp_memory_service.server
from mcp_memory_service.web.app import app as web
from mcp_memory_service.web.api.mcp import _get_memory_server
from mcp_memory_service.utils.startup_orchestrator import check_transport_auth
from mcp_memory_service.utils.agent_context import set_current_agent_id, reset_current_agent_id
from starlette.responses import Response

original_lifespan = web.router.lifespan_context
manager = None

@asynccontextmanager
async def lifespan(app):
    global manager
    async with original_lifespan(app):
        server = _get_memory_server()
        providers = server.storage.embedding_model._model.get_providers()
        if providers != ['CPUExecutionProvider']:
            raise RuntimeError(f'Unexpected embedding providers: {providers}')
        print(f'Embedding: {server.storage.embedding_model_name}; {providers}; one shared storage', flush=True)
        server.remote_transport = True
        manager = StreamableHTTPSessionManager(app=server.server, stateless=True)
        async with manager.run():
            yield

web.router.lifespan_context = lifespan

async def app(scope, receive, send):
    if scope['type'] == 'http':
        headers = dict(scope.get('headers', []))
        host = headers.get(b'host', b'').decode('latin-1')
        origin = headers.get(b'origin', b'').decode('latin-1')
        if host != f'127.0.0.1:{port}' or (origin and origin != f'http://127.0.0.1:{port}'):
            await Response('Invalid Host or Origin', status_code=403)(scope, receive, send)
            return
        if scope.get('path', '').rstrip('/') == '/mcp':
            if not await check_transport_auth(scope, receive, send):
                return
            token = set_current_agent_id(headers.get(b'x-agent-id', b'').decode('latin-1') or None)
            try:
                await manager.handle_request(scope, receive, send)
            finally:
                reset_current_agent_id(token)
            return
    await web(scope, receive, send)

if __name__ == '__main__':
    if not os.environ.get('MCP_API_KEY'):
        raise SystemExit('MCP_API_KEY is required')
    config = uvicorn.Config(app, workers=1, timeout_graceful_shutdown=15, access_log=False)
    asyncio.run(uvicorn.Server(config).serve(sockets=[sock]))
