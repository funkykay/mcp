#!/bin/sh
set -eu
umask 077
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$ROOT/memory.env"
export MCP_API_KEY=$(cat "$ROOT/runtime/api-key")
export MCP_ALLOW_ANONYMOUS_ACCESS=false MCP_OAUTH_ENABLED=false MCP_MDNS_ENABLED=false
export MCP_HTTP_HOST=127.0.0.1 MCP_HTTP_PORT=8000
export MCP_CORS_ORIGINS=http://127.0.0.1:8000
export MCP_MEMORY_ONNX_ALLOW_DOWNLOAD=0
cd "$ROOT/runtime"
exec "$ROOT/.venv/bin/python" "$ROOT/scripts/memory_server.py"
