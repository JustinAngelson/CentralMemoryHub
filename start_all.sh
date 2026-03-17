#!/bin/bash
# Start both Flask (CMH web UI + REST API) and MCP server

echo "=== Central Memory Hub + MCP Server ==="

echo "Starting Flask on :5000..."
gunicorn --bind 0.0.0.0:5000 --workers 2 --timeout 120 main:app &
FLASK_PID=$!

sleep 2

echo "Starting MCP server on :8000..."
MCP_TRANSPORT=streamable_http MCP_PORT=8000 python mcp_server.py &
MCP_PID=$!

echo ""
echo "Flask PID:  $FLASK_PID  →  http://0.0.0.0:5000"
echo "MCP PID:    $MCP_PID  →  http://0.0.0.0:8000/mcp"
echo ""
echo "Public MCP endpoint: https://memory-vault-angelson.replit.app/mcp"
echo ""

trap "kill $FLASK_PID $MCP_PID 2>/dev/null" EXIT

wait -n $FLASK_PID $MCP_PID
EXIT_CODE=$?

echo "A process exited with code $EXIT_CODE — shutting down..."
kill $FLASK_PID $MCP_PID 2>/dev/null
exit $EXIT_CODE
